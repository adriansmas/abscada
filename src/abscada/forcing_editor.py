"""«Forzado»: write a value to any writable variable of the running project, from Studio.

Meant for commissioning and for building an example from scratch: no screen or script is needed.
The value is typed in the cell and written with Enter; it goes through the same runtime write as
an operator command (local variables change at once, PLC variables are sent to the PLC).
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .i18n import tr
from .value_editor import engineering_value

NUMBER, NAME, KIND, CURRENT, FORCE, STATE = range(6)
TRUE_WORDS = {"1", "true", "verdadero", "si", "sí", "on", "yes"}
FALSE_WORDS = {"0", "false", "falso", "no", "off"}


def parse_value(text, kind):
    """Text typed by the engineer -> value of the variable's type."""
    word = text.strip().casefold()
    if kind == "bool":
        if word in TRUE_WORDS:
            return True
        if word in FALSE_WORDS:
            return False
        raise ValueError(tr("Escribe verdadero o falso (1 / 0)"))
    return engineering_value(text, kind)


class ForcingPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.stale = True
        self.building = False
        self.live = None
        self.pending = []          # (row name, Future) of PLC writes waiting for the answer
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("muted")
        top.addWidget(self.notice, 1)
        self.open_runtime = QPushButton(tr("▶  Abrir runtime"))
        self.open_runtime.clicked.connect(lambda: host.start_runtime())
        top.addWidget(self.open_runtime)
        self.search = QLineEdit()
        self.search.setObjectName("searchField")
        self.search.setPlaceholderText(tr("🔍 Filtrar la lista…"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.rebuild)
        top.addWidget(self.search)
        layout.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("N.º"), tr("Variable"), tr("Tipo"), tr("Valor actual"), tr("Forzar a"), tr("Estado")])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(STATE, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self.changed)
        layout.addWidget(self.table, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)

    # --- content -----------------------------------------------------------------------------

    def refresh(self):
        """The project changed: the list is rebuilt when it is next shown."""
        self.stale = True
        if self.isVisible():
            self.rebuild()

    def showEvent(self, event):
        super().showEvent(event)
        if self.stale:
            self.rebuild()

    def runtime(self):
        return self.host.runtime

    def rebuild(self, *args):
        self.stale = False
        runtime = self.runtime()
        self.live = runtime is not None
        self.open_runtime.setVisible(not self.live)
        self.notice.setText(tr("Escribe el valor en «Forzar a» y pulsa Intro. Solo las variables con «Permitir escritura» se pueden forzar.")
                            if self.live else
                            tr("Abre el runtime para poder forzar valores: las variables se escriben mientras está en marcha."))
        query = self.search.text().casefold()
        tags = self.host.project.tags()
        rows = [(name, tag) for name, tag in tags.items() if query in name.casefold()]
        self.building = True
        self.table.setRowCount(len(rows))
        order = {variable["name"]: index + 1 for index, variable in enumerate(self.host.project.variables)}
        for row, (name, tag) in enumerate(rows):
            writable = bool(tag.get("writable", False))
            cells = [str(order.get(name.split(".")[0], "")) if "." not in name else "", name, tag["type"], "", "",
                     "" if writable else tr("Solo lectura")]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                if column == FORCE and writable and self.live:
                    flags |= Qt.ItemFlag.ItemIsEditable
                if column == NUMBER:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setFlags(flags)
                self.table.setItem(row, column, item)
        self.building = False
        self.update_values()

    def update_values(self):
        runtime = self.runtime()
        if runtime is None or not self.table.rowCount():
            return
        samples = runtime.snapshot()
        first = max(0, self.table.rowAt(0))
        last = self.table.rowAt(self.table.viewport().height() - 1)
        last = self.table.rowCount() - 1 if last < 0 else last
        self.building = True
        for row in range(first, last + 1):
            name = self.table.item(row, NAME).text()
            sample = samples.get(name)
            text = "—" if sample is None or sample.quality != "good" else str(sample.value)
            item = self.table.item(row, CURRENT)
            if item.text() != text:
                item.setText(text)
            item.setToolTip("" if sample is None else sample.quality)
        self.building = False

    def tick(self):
        if not self.isVisible():
            return
        if (self.runtime() is not None) != self.live:
            self.rebuild()
            return
        self.update_values()
        still = []
        for name, future in self.pending:
            if not future.done():
                still.append((name, future))
                continue
            try:
                future.result()
                text = tr("Escrito")
            except Exception as exc:
                text = str(exc)
            self.set_state(name, text)
        self.pending = still

    # --- writing -------------------------------------------------------------------------------

    def set_state(self, name, text):
        for row in range(self.table.rowCount()):
            if self.table.item(row, NAME).text() == name:
                self.building = True
                self.table.item(row, STATE).setText(text)
                self.building = False
                return

    def changed(self, item):
        if self.building or item.column() != FORCE or not item.text().strip():
            return
        name = self.table.item(item.row(), NAME).text()
        runtime = self.runtime()
        if runtime is None:
            self.set_state(name, tr("El runtime no está en marcha"))
            return
        try:
            tag = runtime.tags[name]
            future = runtime.write(name, parse_value(item.text(), tag["type"]), actor="studio", origin="forzado")
        except Exception as exc:
            self.set_state(name, str(exc))
            return
        if tag.get("binding"):
            self.set_state(name, tr("Enviado al PLC…"))
            self.pending.append((name, future))
        else:
            self.set_state(name, tr("Escrito"))
        self.update_values()
