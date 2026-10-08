"""Operator alarm and trend controls. SQLite reads run outside the GUI thread."""
import bisect
from collections import deque
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from PySide6.QtCore import Qt, QTimer, QDateTime, QMargins
from PySide6.QtGui import QColor, QPen, QPainter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QDateTimeEdit,
    QSpinBox, QToolButton, QMenu, QScrollArea, QFrame)
from .operational_config import ALARM_COLUMNS, DEFAULT_ALARM_COLUMNS
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QDateTimeAxis, QValueAxis
from .alarms import state
from .storage import ArchiveReader, database_path, ProjectSampleReader
from .i18n import tr, tr_existing
from .project_languages import resolve, default_language, localized
from .runtime_language_ui import runtime_ui
from .flow_layout import FlowLayout

READERS = ThreadPoolExecutor(max_workers=3, thread_name_prefix="abscada-query")
COMMANDS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="abscada-operator")


def stamp(value):
    return datetime.fromtimestamp(value).astimezone().strftime("%d/%m/%Y %H:%M:%S.%f")[:-3] if value is not None else "—"


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else ""


def date_edit(seconds):
    widget = QDateTimeEdit(QDateTime.fromMSecsSinceEpoch(int(seconds*1000)))
    widget.setDisplayFormat("dd/MM/yyyy HH:mm:ss")
    widget.setCalendarPopup(True)
    return widget


def csv_export(parent, rows, columns, filename):
    path, _ = QFileDialog.getSaveFileName(parent, tr("Exportar CSV"), filename, tr("CSV (*.csv)"))
    if not path:
        return
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file); writer.writerow(columns)
            for row in rows:
                writer.writerow([row.get(key, "") for key in columns])
    except OSError as exc:
        QMessageBox.warning(parent, tr("Exportación"), str(exc))


@runtime_ui
class AlarmViewer(QWidget):
    def __init__(self, project, runtime=None, config=None):
        super().__init__()
        self.project, self.runtime = project, runtime
        self.config = config or dict(title=tr("Alarmas"), mode="pending", categories=[], min_priority=1, allow_ack=True)
        self.reader = ArchiveReader(database_path(project))
        self.future = None; self.next_query = 0; self.rows = []; self.token = None
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 6, 8, 6)
        toolbar = FlowLayout()
        self.mode = QComboBox()
        for key, label in (("pending", tr("Pendientes")), ("active", tr("Activas")), ("history", tr("Histórico")), ("events", tr("Eventos"))):
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.config.get("mode", "pending"))))
        self.category = QComboBox(); self.category.addItem(tr("Todas las categorías"), "")
        allowed = self.config.get("categories", [])
        for category in project.alarms["categories"]:
            if not allowed or category["id"] in allowed:
                self.category.addItem(self.project_text(category['name']), category['id'])
        self.search = QLineEdit(); self.search.setPlaceholderText(tr("Mensaje, variable o ID…"))
        self.priority = QSpinBox(); self.priority.setRange(1, 1000); self.priority.setPrefix(tr("Prioridad ≥ "))
        self.priority.setValue(self.config.get("min_priority", 1))
        self.search.setMinimumWidth(140)
        for widget in (self.mode, self.category, self.priority, self.search):
            toolbar.addWidget(widget)
        layout.addLayout(toolbar)
        row = FlowLayout()
        self.date_controls = QWidget(); self.date_controls.setLayout(row)
        row.setContentsMargins(0,0,0,0)
        self.start = date_edit(time.time()-86400); self.end = date_edit(time.time())
        row.addWidget(QLabel(tr("Desde"))); row.addWidget(self.start); row.addWidget(QLabel(tr("Hasta"))); row.addWidget(self.end)
        self.apply = QPushButton(tr("Consultar")); self.apply.clicked.connect(self.reload); row.addWidget(self.apply)
        self.export = QPushButton(tr("CSV")); self.export.clicked.connect(self.export_csv); toolbar.addWidget(self.export)
        layout.addWidget(self.date_controls)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([tr_existing(label) for _,label in ALARM_COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        columns = QToolButton(); columns.setText(tr("Columnas"))
        menu = QMenu(columns)
        for index,(key,title) in enumerate(ALARM_COLUMNS):
            action = menu.addAction(tr_existing(title)); action.setCheckable(True)
            visible = key in self.config.get("columns",DEFAULT_ALARM_COLUMNS)
            action.setChecked(visible); self.table.setColumnHidden(index,not visible)
            action.toggled.connect(lambda checked, i=index: self.table.setColumnHidden(i,not checked))
        columns.setMenu(menu); columns.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(columns)
        layout.addWidget(self.table, 1)
        footer = FlowLayout()
        self.count = QLabel(); footer.addWidget(self.count)
        self.actor = QLineEdit(tr("Operador")); self.actor.setMaximumWidth(170)
        self.actor.setPlaceholderText(tr("Operador"))
        self.comment = QLineEdit(); self.comment.setPlaceholderText(tr("Comentario de ACK"))
        self.ack = QPushButton(tr("ACK selección")); self.ack.clicked.connect(self.ack_selected)
        self.ack_visible = QPushButton(tr("ACK visibles")); self.ack_visible.clicked.connect(self.ack_all_visible)
        for widget in (self.actor, self.comment, self.ack, self.ack_visible):
            footer.addWidget(widget)
            widget.setVisible(runtime is not None and self.config.get("allow_ack", True))
        layout.addLayout(footer)
        self.mode.currentIndexChanged.connect(self.reload); self.category.currentIndexChanged.connect(self.reload)
        self.priority.valueChanged.connect(self.reload); self.search.textChanged.connect(self.populate)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(200)
        self.reload()

    def reload(self, *args):
        self.next_query = 0
        historical = self.mode.currentData() in {"history", "events"}
        self.date_controls.setVisible(historical)
        for widget in (self.start, self.end, self.apply):
            widget.setEnabled(historical)
        self.token = None

    def parameters(self):
        selected = self.category.currentData()
        categories = (selected,) if selected else tuple(self.config.get("categories", []))
        return (self.mode.currentData(), categories, max(self.priority.value(), self.config.get("min_priority", 1)),
                self.start.dateTime().toMSecsSinceEpoch()/1000, self.end.dateTime().toMSecsSinceEpoch()/1000)

    def poll(self):
        code = self.runtime.language if self.runtime else default_language(self.project)
        if getattr(self, 'displayed_language', None) != code:
            self.displayed_language = code
            names = {c['id']: self.project_text(c['name']) for c in self.project.alarms['categories']}
            for index in range(1, self.category.count()):
                self.category.setItemText(index, names.get(self.category.itemData(index), ''))
            self.populate()
        pending = getattr(self, 'ack_future', None)
        if pending is not None and pending.done():
            self.ack_future = None
            try:
                pending.result(); self.next_query = 0
            except Exception as exc:
                self.count.setText(str(exc))
            self.ack.setEnabled(True); self.ack_visible.setEnabled(True)
        if self.future and self.future.done():
            try:
                token, rows = self.future.result()
                if token == self.parameters():
                    self.rows = rows; self.populate()
            except Exception as exc:
                self.count.setText(str(exc))
            self.future = None
        if self.future is None and time.monotonic() >= self.next_query and self.isVisible():
            args = self.parameters()
            if args[0] in {"history","events"} and args[3]>=args[4]:
                self.rows=[]; self.populate()
                self.count.setText(tr("El inicio debe ser anterior al final"))
                return
            self.future = READERS.submit(lambda: (args, self.reader.alarms(*args)))
            self.next_query = time.monotonic()+1

    def project_text(self, value):
        return resolve(value, self.runtime.language if self.runtime else default_language(self.project), default_language(self.project))

    def translated_rows(self):
        definitions = {a['id']: a for a in self.project.alarms['items']}
        result = []
        for row in self.rows:
            alarm = dict(row)
            message = definitions.get(row['alarm_id'], {}).get('message', row['message'])
            if isinstance(message, str) and message.startswith('{'):
                try:
                    message = json.loads(message)
                except ValueError:
                    pass
            alarm['message'] = self.project_text(message)
            result.append(alarm)
        return result

    def populate(self, *args):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.table.selectedItems()}
        needle = self.search.text().casefold()
        rows = [r for r in self.translated_rows() if needle in f"{r['message']} {r['tag']} {r['alarm_id']}".casefold()]
        self.table.setSortingEnabled(False); self.table.setRowCount(len(rows))
        names = {c["id"]: self.project_text(c["name"]) for c in self.project.alarms["categories"]}
        colors = {c["id"]: c.get("color", "#d74c4c") for c in self.project.alarms["categories"]}
        samples = self.runtime.snapshot() if self.runtime else {}
        for index, alarm in enumerate(rows):
            event = alarm.get("event")
            status = {"incoming": tr("Entrada"), "outgoing": tr("Salida"), "ack": "ACK", "disabled": tr("Deshabilitada")}.get(event, event) if event else state(alarm)
            quality = samples[alarm["tag"]].quality if alarm["tag"] in samples else "—"
            texts = [alarm["priority"], names.get(alarm["category"], alarm["category"]), alarm["message"], alarm["tag"], status,
                     stamp(alarm["entered_at"]), stamp(alarm["returned_at"]), stamp(alarm["ack_at"]), alarm.get("actor") or alarm.get("ack_by") or "—", quality]
            if event:
                texts[5] = stamp(alarm["timestamp"])
            for column, text in enumerate(texts):
                item = QTableWidgetItem(str(text))
                item.setData(Qt.ItemDataRole.UserRole, alarm["id"])
                if column == 0:
                    item.setData(Qt.ItemDataRole.DisplayRole, alarm["priority"])
                if alarm["ack_required"] and alarm["ack_at"] is None:
                    item.setForeground(QColor(colors.get(alarm["category"], "#d74c4c")))
                self.table.setItem(index, column, item)
            if alarm["id"] in selected:
                self.table.selectRow(index)
        self.table.setSortingEnabled(True)
        self.count.setText(f"{len(rows)} registros" + (tr(" · límite 2000; acota la consulta") if len(self.rows) == 2000 else ""))
        enabled = self.runtime is not None and self.runtime.operations is not None and self.config.get("allow_ack", True) and getattr(self, 'ack_future', None) is None
        self.ack.setEnabled(enabled); self.ack_visible.setEnabled(enabled)
        security = getattr(self.runtime, "security", None)
        if security is not None and security.enabled:
            # The ACK is signed by the logged-in operator, not by a free text field.
            session = self.runtime.session
            self.actor.setReadOnly(True)
            self.actor.setText(session.user if session else tr("Sin sesión"))

    def acknowledge(self, ids):
        if getattr(self, 'ack_future', None) is not None or not self.runtime or not self.runtime.operations:
            return
        actor = self.actor.text().strip()
        security = getattr(self.runtime, "security", None)
        if security is not None and security.enabled:
            session = self.runtime.session
            if not security.permits(session, "acknowledge"):
                self.count.setText(tr("Inicia sesión con un usuario que pueda reconocer alarmas"))
                return
            security.touch(session)
            actor = session.user
        self.ack_future = COMMANDS.submit(self.runtime.operations.acknowledge, set(ids), actor, self.comment.text().strip())
        self.ack.setEnabled(False); self.ack_visible.setEnabled(False)

    def ack_selected(self):
        self.acknowledge({item.data(Qt.ItemDataRole.UserRole) for item in self.table.selectedItems()})

    def ack_all_visible(self):
        self.acknowledge({self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(self.table.rowCount())})

    def export_csv(self):
        rows = []
        visible = {self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())}
        for row in self.translated_rows():
            if row["id"] in visible:
                row = dict(row)
                for key in ("entered_at", "returned_at", "ack_at", "timestamp"):
                    if key in row:
                        row[key] = utc(row[key])
                rows.append(row)
        columns = ["alarm_id", "message", "category", "priority", "tag", "entered_at", "returned_at", "ack_at", "ack_by", "value"]
        if self.mode.currentData() == "events":
            columns += ["event", "timestamp", "actor", "comment"]
        csv_export(self, rows, columns, "alarmas.csv")


class TrendChartView(QChartView):
    def __init__(self, chart, host):
        super().__init__(chart)
        self.host = host
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRubberBand(QChartView.RubberBand.RectangleRubberBand)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        self.press_point = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if hasattr(self, "press_point") and (event.position()-self.press_point).manhattanLength() > 5:
            self.host.start.setDateTime(self.host.x_axis.min())
            self.host.end.setDateTime(self.host.x_axis.max())
            self.host.live.setChecked(False)
            self.host.reload()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.chart().series():
            return
        position = self.chart().mapToValue(event.position(), self.chart().series()[0])
        self.host.cursor(position.x()/1000)


@runtime_ui
class TrendViewer(QWidget):
    def __init__(self, project, config, runtime=None):
        super().__init__()
        self.source_config = config
        config = localized(config, runtime.language if runtime else default_language(project), default_language(project))
        self.project, self.config, self.runtime = project, config, runtime
        self.buffer = {c["tag"]: deque(maxlen=50000) for c in config["curves"]}
        self.tag_types = {name: tag["type"] for name, tag in project.tags().items()}
        self.reader = ProjectSampleReader(project)
        self.future, self.next_query, self.data = None, 0, {}
        self.export_future = None
        self.generation = 0
        layout = QVBoxLayout(self); layout.setContentsMargins(6, 4, 6, 4)
        toolbar = FlowLayout()
        self.source = QComboBox()
        self.source.addItem(tr("Tiempo real"), "live"); self.source.addItem(tr("Histórico"), "history")
        self.source.setCurrentIndex(0 if runtime else 1)
        self.source.setEnabled(runtime is not None)
        toolbar.addWidget(self.source)
        self.live = QCheckBox(tr("Seguir")); self.live.setChecked(True)
        self.start = date_edit(time.time()-config.get("window_seconds", 600)); self.end = date_edit(time.time())
        self.start.setMaximumWidth(180); self.end.setMaximumWidth(180)
        for widget in (self.live, self.start, self.end):
            toolbar.addWidget(widget)
        self.query = QPushButton(tr("Consultar")); self.query.clicked.connect(self.reload); toolbar.addWidget(self.query)
        fit = QPushButton(tr("Restablecer zoom")); fit.clicked.connect(lambda: self.chart.zoomReset()); toolbar.addWidget(fit)
        export = QPushButton(tr("CSV")); export.clicked.connect(self.export_csv); toolbar.addWidget(export)
        layout.addLayout(toolbar)
        self.chart = QChart(); self.chart.setTitle(config["title"])
        self.chart.legend().hide(); self.chart.setBackgroundBrush(QColor("#ffffff"))
        self.chart.setMargins(QMargins(4, 4, 4, 4))
        self.x_axis = QDateTimeAxis(); self.x_axis.setFormat("HH:mm:ss"); self.x_axis.setTickCount(6)
        # Qt needs a non-degenerate datetime range when creating its axis graphics.
        now = QDateTime.currentDateTime()
        self.x_axis.setRange(now.addMSecs(-int(config.get("window_seconds",600)*1000)), now)
        self.chart.addAxis(self.x_axis, Qt.AlignmentFlag.AlignBottom)
        self.axes, self.curve_visible, self.axis_checks = {}, {}, {}
        for axis in config["axes"]:
            widget = QValueAxis(); widget.setTitleText(axis.get("title", axis["id"]))
            widget.setRange(axis.get("min", 0), axis.get("max", 100))
            self.chart.addAxis(widget, Qt.AlignmentFlag.AlignLeft if axis.get("side", "left") == "left" else Qt.AlignmentFlag.AlignRight)
            widget.setTitleVisible(len(config["axes"]) <= 4)  # many axes: the toggles below name them
            widget.setVisible(axis.get("visible", True)); self.axes[axis["id"]] = widget
        self.view = TrendChartView(self.chart, self); layout.addWidget(self.view, 1)
        # Any number of curves: the toggles wrap onto new rows, and past a few rows they scroll.
        toggles = FlowLayout()
        for curve in config["curves"]:
            check = QCheckBox(curve.get("title", curve["tag"]))
            check.setChecked(curve.get("visible", True)); check.setStyleSheet(f"color: {curve.get('color', '#147d75')};")
            self.curve_visible[curve["id"]] = check
            check.toggled.connect(self.draw)
            toggles.addWidget(check)
        toggles.addWidget(QLabel(tr("Ejes:")))
        for axis in config["axes"]:
            check = QCheckBox(axis.get("title", axis["id"]))
            check.setChecked(axis.get("visible", True))
            self.axis_checks[axis["id"]] = check
            check.toggled.connect(self.axes[axis["id"]].setVisible)
            toggles.addWidget(check)
        holder = QWidget(); holder.setLayout(toggles)
        scroller = QScrollArea(); scroller.setWidget(holder); scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame); scroller.setMaximumHeight(96)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroller)
        self.readout = QLabel("—"); layout.addWidget(self.readout)
        self.live.toggled.connect(self.reload)
        self.source.currentIndexChanged.connect(self.reload)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(200)
        self.reload()

    def reload(self, *args):
        self.generation += 1; self.next_query = 0
        for widget in (self.start, self.end, self.query):
            widget.setEnabled(not self.live.isChecked())

    def poll(self):
        code = self.runtime.language if self.runtime else default_language(self.project)
        if getattr(self, 'displayed_language', None) != code:
            self.displayed_language = code
            self.config = localized(self.source_config, code, default_language(self.project))
            self.chart.setTitle(self.config['title'])
            for axis in self.config['axes']:
                title = axis.get('title', axis['id'])
                self.axes[axis['id']].setTitleText(title)
                self.axis_checks[axis['id']].setText(title)
            for curve in self.config['curves']:
                self.curve_visible[curve['id']].setText(curve.get('title', curve['tag']))
            self.draw()
        if self.export_future and self.export_future.done():
            try:
                count = self.export_future.result()
                self.readout.setText(tr("CSV exportado: {count} registros", count=count))
            except Exception as exc:
                QMessageBox.warning(self, tr("Exportación"), str(exc))
            self.export_future = None
        if self.future and self.future.done():
            try:
                generation, start, end, data = self.future.result()
                if generation == self.generation:
                    self.data, self.range = data, (start, end)
                    self.draw()
            except Exception as exc:
                self.readout.setText(str(exc))
            self.future = None
        if self.runtime:
            now = time.time()
            snapshot = self.runtime.snapshot()
            for tag, buffer in self.buffer.items():
                sample = snapshot.get(tag)
                if sample is None:
                    continue
                numeric = float(sample.value) if isinstance(sample.value, (int, float)) else None
                buffer.append(dict(tag=tag, recorded_at=now, source_at=sample.timestamp,
                    value=json.dumps(sample.value), numeric=numeric, quality=sample.quality))
                while buffer and buffer[0]["recorded_at"] < now-self.config.get("window_seconds", 600):
                    buffer.popleft()
            if self.source.currentData() == "live":
                end = now if self.live.isChecked() else self.end.dateTime().toMSecsSinceEpoch()/1000
                start = end-self.config.get("window_seconds", 600) if self.live.isChecked() else self.start.dateTime().toMSecsSinceEpoch()/1000
                if start >= end:
                    self.readout.setText(tr("El inicio debe ser anterior al final")); return
                self.data = {tag: [row for row in buffer if start <= row["recorded_at"] <= end] for tag, buffer in self.buffer.items()}
                self.range = (start, end)
                if self.isVisible():
                    self.draw()
                return
        if self.future is None and self.isVisible() and time.monotonic() >= self.next_query:
            end = time.time() if self.live.isChecked() else self.end.dateTime().toMSecsSinceEpoch()/1000
            start = end-self.config.get("window_seconds", 600) if self.live.isChecked() else self.start.dateTime().toMSecsSinceEpoch()/1000
            if start >= end:
                self.readout.setText(tr("El inicio debe ser anterior al final")); return
            generation = self.generation
            tags = {c["tag"] for c in self.config["curves"]}
            self.future = READERS.submit(lambda: (generation, start, end, {tag: self.reader.samples(tag, start, end) for tag in tags}))
            self.next_query = time.monotonic()+1 if self.live.isChecked() else float("inf")

    def draw(self, *args):
        self.chart.removeAllSeries()
        if not hasattr(self, "range"):
            return
        axis_values = {key: [] for key in self.axes}
        count = 0
        for curve in self.config["curves"]:
            if not self.curve_visible[curve["id"]].isChecked():
                continue
            series = None
            for row in self.data.get(curve["tag"], []):
                if row["quality"] != "good" or row["numeric"] is None:
                    series = None; continue
                if series is None:
                    series = QLineSeries(); series.setName(curve["tag"])
                    series.setPen(QPen(QColor(curve.get("color", "#147d75")), curve.get("width", 2)))
                    self.chart.addSeries(series); series.attachAxis(self.x_axis); series.attachAxis(self.axes[curve["axis"]])
                if self.tag_types[curve["tag"]] == "bool" and series.count():
                    series.append(row["recorded_at"]*1000, series.at(series.count()-1).y())
                series.append(row["recorded_at"]*1000, row["numeric"])
                axis_values[curve["axis"]].append(row["numeric"]); count += 1
        for series in self.chart.series():
            series.setPointsVisible(series.count() == 1)
        self.x_axis.setRange(QDateTime.fromMSecsSinceEpoch(int(self.range[0]*1000)), QDateTime.fromMSecsSinceEpoch(int(self.range[1]*1000)))
        self.x_axis.setFormat("dd/MM HH:mm" if self.range[1]-self.range[0] >= 86400 else "HH:mm:ss")
        if self.live.isChecked():
            self.start.setDateTime(self.x_axis.min()); self.end.setDateTime(self.x_axis.max())
        for axis in self.config["axes"]:
            values = axis_values[axis["id"]]
            if axis.get("auto", True) and values:
                lo, hi = min(values), max(values); pad = max((hi-lo)*0.08, abs(hi)*0.01, 0.1)
                self.axes[axis["id"]].setRange(lo-pad, hi+pad)
        self.readout.setText(tr("{count} puntos · {stamp} — {stamp2}", count=count, stamp=stamp(self.range[0]), stamp2=stamp(self.range[1])))

    def cursor(self, timestamp):
        values = [stamp(timestamp)]
        for curve in self.config["curves"]:
            rows = self.data.get(curve["tag"], [])
            if not rows or not self.curve_visible[curve["id"]].isChecked():
                continue
            index = bisect.bisect_left([row["recorded_at"] for row in rows], timestamp)
            candidates = rows[max(0,index-1):min(len(rows), index+1)]
            row = min(candidates, key=lambda r: abs(r["recorded_at"]-timestamp))
            values.append(f"{curve['tag']}: {json.loads(row['value'])} ({row['quality']})")
        self.readout.setText("  ·  ".join(values))

    def export_csv(self):
        if not hasattr(self, "range"):
            return
        if self.export_future:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Exportar CSV"), "tendencia.csv", tr("CSV (*.csv)"))
        if not path:
            return
        start, end = self.range
        tags = {c["tag"] for c in self.config["curves"]}
        live_rows = [dict(row) for tag in tags for row in self.data.get(tag, [])] if self.source.currentData() == "live" else None
        def export():
            rows = live_rows if live_rows is not None else [row for tag in tags for row in self.reader.raw_samples(tag, start, end)]
            if len(rows) > 100000:
                raise ValueError(tr("La exportación supera 100000 registros; acota el intervalo"))
            rows.sort(key=lambda row: (row["recorded_at"], row["tag"]))
            for row in rows:
                row["recorded_at"] = utc(row["recorded_at"]); row["source_at"] = utc(row["source_at"])
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, ["tag", "recorded_at", "source_at", "value", "quality"])
                writer.writeheader(); writer.writerows({key: row[key] for key in writer.fieldnames} for row in rows)
            return len(rows)
        self.export_future = READERS.submit(export)
