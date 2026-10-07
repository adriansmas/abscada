"""Runtime windows share one acquisition service and frozen project snapshot."""
from __future__ import annotations
import copy
import time
from PySide6.QtCore import QTimer, Signal, Qt, QEvent, QPoint, QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QInputDialog, QMessageBox
from .theme import STYLE, configure_fonts
from .graphics import CanvasScene, CanvasView, ElementItem
from .runtime import Runtime
from .viewers import AlarmViewer, TrendViewer
from .operation_windows import MAIN_MODE, popup_key, popup_title, settings_key


def monitors():
    """Operator numbering: monitor 1 is the left-most screen, then top to bottom."""
    return sorted(QGuiApplication.screens(), key=lambda s: (s.geometry().x(), s.geometry().y()))


class RuntimeWindow(QMainWindow):
    closed = Signal()
    diagnostic = Signal(str)
    design_mode = False

    def __init__(self, project, screen=None, *, owner=None, faceplate=None):
        super().__init__(owner, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.owner = owner
        self.popups = {}
        self.momentary = {}
        self.release_futures = []
        self.containers = {}
        self.settings_key = None
        self.project = owner.project if owner else copy.deepcopy(project)
        self.runtime = owner.runtime if owner else Runtime(self.project)
        self.samples = self.runtime.snapshot()
        # A faceplate pop-up shows one template instance instead of a project screen.
        self.faceplate = faceplate
        self.document_name = "" if faceplate else screen or project.manifest["startup_screen"]
        self.running = False
        self.last_script_log = 0
        self.setFont(configure_fonts())
        self.setStyleSheet(STYLE)
        self.setWindowTitle("abSCADA Runtime · " + self.project.manifest["name"])
        self.resize(1180, 820)
        self.scene = CanvasScene(self)
        self.view = CanvasView(self.scene, self)
        self.view.scale_mode = self.project.manifest.get("display", {}).get("main", {}).get("scale", "fit")
        self.setCentralWidget(self.view)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.session_label = self.session_button = None
        if not owner and self.runtime.security.enabled:
            from PySide6.QtWidgets import QLabel, QPushButton
            self.session_label = QLabel(); self.session_label.setObjectName("session_label")
            self.session_button = QPushButton(); self.session_button.setObjectName("session_button")
            self.session_button.clicked.connect(self.toggle_session)
            self.statusBar().addPermanentWidget(self.session_label)
            self.statusBar().addPermanentWidget(self.session_button)
            self.update_session_widgets()
        self.render_scene()

    # -- operator session (root window only; pop-ups share it) --------------
    def update_session_widgets(self):
        if self.session_label is None:
            return
        session = self.runtime.session
        self.session_label.setText(f"Usuario: {session.display}" if session else "Sin sesión · solo lectura")
        self.session_button.setText("Cerrar sesión" if session else "Iniciar sesión")

    def toggle_session(self):
        if self.runtime.session:
            self.runtime.logout()
            self.statusBar().showMessage("Sesión cerrada", 5000)
        else:
            self.request_login()
        self.update_session_widgets()

    def request_login(self, reason=""):
        from .login_dialog import LoginDialog
        root = self.owner or self
        dialog = LoginDialog(self.runtime, self, reason)
        accepted = dialog.exec() == LoginDialog.DialogCode.Accepted
        root.update_session_widgets()
        return accepted

    def authorize(self, element):
        """Make sure the operator may use this control; offers to log in if not."""
        from .security import PERMISSIONS, required_permission
        permission = required_permission(element)
        security = self.runtime.security
        if security.permits(self.runtime.session, permission):
            return True
        if self.runtime.session and not security.expired(self.runtime.session):
            raise PermissionError(f"El usuario {self.runtime.session.user} no tiene el permiso «{PERMISSIONS[permission]}»")
        if not self.request_login(f"Esta orden necesita el permiso «{PERMISSIONS[permission]}»."):
            return False
        if not security.permits(self.runtime.session, permission):
            raise PermissionError(f"El usuario {self.runtime.session.user} no tiene el permiso «{PERMISSIONS[permission]}»")
        return True

    def start(self):
        if not self.owner:
            self.runtime.start()
        self.running = True
        self.timer.start(100)
        self.opened()

    def opened(self):
        if not self.faceplate:
            self.screen_opened(self.document_name)
        for container in self.containers.values():
            self.screen_opened(container.document_name)

    def show_operation(self):
        """Show the main window and the start-up windows configured per monitor."""
        display = self.project.manifest.get("display", {})
        main = display.get("main", {})
        self.settings_key = settings_key(self.project, "main")
        self.place(1180, 820, main)
        self.show_mode(main.get("mode", MAIN_MODE))
        for index, window in enumerate(display.get("windows", [])):
            self.present(f"display_{index}", dict(screen=window["screen"]), options=window)

    def show_mode(self, mode):
        {"maximized": self.showMaximized, "fullscreen": self.showFullScreen}.get(mode, self.show)()

    def monitor(self, number):
        if number is None:
            return None
        screens = monitors()
        if number <= len(screens):
            return screens[number - 1]
        self.diagnostic.emit(f"Monitor {number} no disponible; se usa el principal")
        return QGuiApplication.primaryScreen()

    def place(self, width, height, options=None, anchor=None, cascade=0):
        """Remembered position first; a configured monitor still wins if the
        remembered position lies elsewhere (screens removed or changed)."""
        options = options or {}
        if options.get("on_top"):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        monitor = self.monitor(options.get("monitor"))
        saved = QSettings("abSCADA", "Runtime").value(self.settings_key) if self.settings_key else None
        if saved is not None and self.restoreGeometry(saved):
            if monitor is None or monitor.geometry().contains(self.frameGeometry().center()):
                return
        screen = monitor or (anchor.screen() if anchor else self.screen())
        available = screen.availableGeometry()
        self.resize(min(max(320, int(width)), max(320, available.width() - 80)),
                    min(max(240, int(height)), max(240, available.height() - 100)))
        center = anchor.frameGeometry().center() if anchor and monitor is None else available.center()
        position = center - self.rect().center() + QPoint(cascade, cascade)
        self.move(max(available.left(), min(position.x(), available.right() - self.width())),
                  max(available.top(), min(position.y(), available.bottom() - self.height())))

    def save_geometry(self):
        if self.settings_key:
            QSettings("abSCADA", "Runtime").setValue(self.settings_key, self.saveGeometry())

    def open_popup(self, screen, modal=False, window=None):
        root = self.owner or self
        if screen not in root.project.screens:
            raise ValueError("Pantalla emergente inexistente")
        return root.present(screen, dict(screen=screen), modal, window)

    def open_faceplate(self, template, bindings, title="", modal=False, window=None):
        """Faceplate of one equipment in its own window; each equipment gets its own."""
        root = self.owner or self
        if template not in root.project.faceplates:
            raise ValueError("Faceplate emergente inexistente")
        bindings = dict(bindings)
        target = dict(faceplate=dict(template=template, bindings=bindings,
                                     title=popup_title(root.project, template, bindings, title)))
        return root.present(popup_key(template, bindings), target, modal, window)

    def present(self, key, target, modal=False, options=None):
        if not self.running:
            return None
        options = options or {}
        popup = self.popups.get(key)
        created = popup is None
        if created:
            popup = RuntimeWindow(self.project, target.get("screen"), owner=self, faceplate=target.get("faceplate"))
            self.popups[key] = popup
            popup.diagnostic.connect(self.diagnostic.emit)
            popup.diagnostic.connect(lambda message:self.statusBar().showMessage(message,15000))
            popup.closed.connect(lambda key=key: self.popups.pop(key, None))
            popup.settings_key = settings_key(self.project, key)
            # Several units of the same faceplate must not open exactly on top of each other.
            siblings = sum(1 for other in self.popups if isinstance(key, tuple) and isinstance(other, tuple)
                           and other[1] == key[1] and other != key)
            document = popup.screen_document()
            popup.place(document["width"], document["height"], options, anchor=self, cascade=30 * siblings)
            popup.start()
        else:
            popup.show_target(target)
        modality = Qt.WindowModality.WindowModal if modal else Qt.WindowModality.NonModal
        if popup.windowModality() != modality:
            popup.hide()
            popup.setWindowModality(modality)
        if created:
            popup.show_mode(options.get("mode", "normal"))
        elif popup.isMinimized():
            popup.showNormal()
        else:
            popup.show()
        popup.raise_(); popup.activateWindow()
        return popup

    def show_target(self, target):
        if "faceplate" in target:
            if self.faceplate != target["faceplate"]:
                self.faceplate = target["faceplate"]
                self.document_name = ""
                self.render_scene()
        elif self.faceplate or self.document_name != target["screen"]:
            self.select_screen(target["screen"])

    def screen_document(self):
        if not self.faceplate:
            return self.project.screens[self.document_name]
        template = self.project.faceplates[self.faceplate["template"]]
        return dict(title=self.faceplate["title"], width=template["width"], height=template["height"],
                    background=template.get("background", "#ffffff"),
                    elements=[dict(id="faceplate", kind="faceplate", x=0, y=0, w=template["width"],
                                   h=template["height"], template=self.faceplate["template"],
                                   bindings=self.faceplate["bindings"])])

    def defer(self, callback):
        # The clicked graphic may be deleted by navigation/closing. Finish its
        # mouse event first and discard requests if this window has since closed.
        QTimer.singleShot(0, lambda: callback() if self.running else None)

    def select_screen(self, screen):
        self.faceplate = None
        self.document_name = screen
        self.render_scene()

    def render_scene(self):
        self.release_momentaries()
        self.containers.clear()
        self.scene.clear()
        document = self.screen_document()
        title = document.get("title") or self.document_name
        self.setWindowTitle(title if self.owner else "abSCADA Runtime · " + self.project.manifest["name"] + " · " + title)
        self.scene.setSceneRect(0, 0, document["width"], document["height"])
        for element in self.project.expand(document["elements"]):
            self.scene.addItem(ElementItem(self, element))
        self.view.fit_canvas()
        if self.running:
            self.opened()

    def screen_opened(self, screen):
        for name in self.project.screens[screen].get('on_open', []):
            self.runtime.scripts.submit(name, 'screen_open', screen)

    def refresh(self):
        self.check_releases()
        self.samples = self.runtime.snapshot()
        for scene in [self.scene]+[c.scene for c in self.containers.values()]:
            for item in scene.items():
                if isinstance(item,ElementItem): item.refresh_state()
            scene.update()
        if not self.owner:
            for result in self.runtime.scripts.diagnostics():
                if result['time'] <= self.last_script_log:
                    continue
                self.last_script_log = result['time']
                if result['status'] == 'error':
                    detail = result['message'].strip().splitlines() or ['Error de ejecución']
                    text = f"Script {result['script']}: {detail[-1]}"
                    self.diagnostic.emit(text)
                    self.statusBar().showMessage(text, 15000)
                    for popup in self.popups.values():
                        popup.statusBar().showMessage(text, 15000)
        if self.runtime.operations and self.runtime.operations.error:
            self.statusBar().showMessage(self.runtime.operations.error)
        if not self.owner and self.runtime.session and self.runtime.security.expired(self.runtime.session):
            self.release_momentaries()
            self.runtime.logout("session_timeout")
            self.update_session_widgets()
            self.statusBar().showMessage("Sesión cerrada por inactividad", 15000)
        if not self.owner and self.runtime.opcua and self.runtime.opcua.error:
            self.statusBar().showMessage(self.runtime.opcua.error)
        for name, success, message in ([] if self.owner else self.runtime.write_results()):
            text = f"{name}: {'OK' if success else 'ERROR'} · {message}"
            self.diagnostic.emit(text)
            if not success:
                self.statusBar().showMessage(text, 10000)
                for popup in self.popups.values():
                    popup.statusBar().showMessage(text, 10000)

    def navigate_screen(self, screen, target='', source=None):
        if target == '__window__':
            destination = self
        elif target:
            destination = self.containers.get(target)
            if destination is None:
                raise ValueError(f'El contenedor {target} no está en esta ventana')
        else:
            destination = source or self
        destination.select_screen(screen)

    def release_momentaries(self):
        for element in list(self.momentary.values()): self.actuate(element,phase='release')
        for container in self.containers.values():
            for item in container.scene.items():
                if isinstance(item,ElementItem): item.pressed=False
        if hasattr(self,'scene'):
            for item in self.scene.items():
                if isinstance(item,ElementItem): item.pressed=False

    def check_releases(self,wait=False):
        pending=[];deadline=time.monotonic()+2
        for name,future in self.release_futures:
            if not wait and not future.done():pending.append((name,future));continue
            try:future.result(timeout=max(0,deadline-time.monotonic()) if wait else 0)
            except Exception as exc:
                message=f'Liberación no confirmada por el transporte: {name}. {exc}'
                self.diagnostic.emit(message);self.statusBar().showMessage(message,15000)
        self.release_futures=pending

    def event(self,event):
        if event.type()==QEvent.Type.WindowDeactivate and hasattr(self,'momentary'):
            self.release_momentaries()
        return super().event(event)

    def actuate(self, element, entry=False, source=None, phase=None):
        try:
            if element.get('action') in {'momentary','press_release'} and phase=='release':
                if id(element) in self.momentary:
                    self.momentary.pop(id(element))
                    try:
                        tag=self.runtime.tags[element['tag']]
                        if tag.get('binding') and self.runtime.snapshot()[element['tag']].quality!='good':
                            raise ValueError('Sin comunicación; liberación no enviada')
                        # Releases are never refused: a pressed command must always be able to stop.
                        future=self.runtime.write(element['tag'],element.get('release_value',False),
                                                  actor=self.runtime.security.actor(self.runtime.session),origin='hmi')
                        self.release_futures.append((element['tag'],future))
                    except Exception as exc:
                        message=f"No se pudo enviar la liberación de {element['tag']}: {exc}"
                        self.diagnostic.emit(message); self.statusBar().showMessage(message,15000)
                return
            from .dynamics import permitted
            samples=self.runtime.snapshot()
            if not permitted(element,samples,'visible') or not permitted(element,samples,'enabled'):
                raise ValueError(element.get('dynamics',{}).get('disabled_reason','No se cumple el permiso de operación'))
            if phase == 'press':
                # No modal dialog while the mouse holds a momentary button: just refuse.
                from .security import required_permission
                if not self.runtime.security.permits(self.runtime.session, required_permission(element)):
                    (self.owner or self).statusBar().showMessage("Inicia sesión con un usuario autorizado para usar este pulsador", 8000)
                    return
            elif not self.authorize(element):
                return
            action = element.get("action")
            if action == 'script':
                self.runtime.scripts.submit(element['script'], 'button', source.document_name if source else self.document_name)
                return
            if action in {"screen", "popup"}:
                target = element.get("screen", "")
                if target not in self.project.screens:
                    raise ValueError("Pantalla inexistente")
                if action == "popup":
                    self.defer(lambda: self.open_popup(target, element.get("modal", False), element.get("window")))
                else:
                    container = element.get('target_container', '')
                    def navigate():
                        try:
                            self.navigate_screen(target, container, source)
                        except (ValueError, RuntimeError) as exc:
                            self.statusBar().showMessage(str(exc), 10000)
                    self.defer(navigate)
                return
            if action == "faceplate_popup":
                template, bindings = element["template"], dict(element.get("bindings", {}))
                title, modal, window = element.get("title", ""), element.get("modal", False), element.get("window")
                self.defer(lambda: self.open_faceplate(template, bindings, title, modal, window))
                return
            if action == "close_popup":
                if self.owner:
                    self.defer(self.close)
                return
            name = element.get("tag", "")
            if name not in self.runtime.tags:
                raise ValueError("Este control no tiene una variable configurada")
            sample = self.runtime.snapshot()[name]
            if self.runtime.tags[name].get("binding") and sample.quality != "good":
                raise ValueError("La variable no tiene una lectura válida")
            if entry:
                value, ok = QInputDialog.getText(self, "Escribir valor", name, text=str(sample.value))
                if not ok:
                    return
            elif element.get("action", "toggle") == "toggle":
                if self.runtime.tags[name]["type"] != "bool":
                    raise ValueError("La acción alternar necesita una variable bool")
                value = not sample.value
            elif element.get('action') in {'momentary','press_release'}:
                if phase!='press': return
                value=element.get('press_value',True)
            elif element.get("action") == "set":
                value = element["value"]
            else:
                raise ValueError("Acción de botón desconocida")
            if entry:
                from .value_editor import engineering_value
                value=engineering_value(value,self.runtime.tags[name]['type'])
            self.runtime.command(name, value, self.runtime.session)
            if element.get('action') in {'momentary','press_release'}: self.momentary[id(element)]=element
        except Exception as exc:
            QMessageBox.warning(self, "Operación no realizada", str(exc))

    def closeEvent(self, event):
        try:
            self.release_momentaries()
            for popup in list(self.popups.values()): popup.release_momentaries()
            self.check_releases(wait=True)
            for popup in list(self.popups.values()):popup.check_releases(wait=True)
            if self.running and not self.owner:
                self.runtime.stop()
            for popup in list(self.popups.values()):
                popup.close()
            self.save_geometry()
            self.running = False
            self.timer.stop()
            for viewer in self.findChildren(AlarmViewer) + self.findChildren(TrendViewer):
                viewer.timer.stop()
            self.closed.emit()
            event.accept()
        except TimeoutError as exc:
            self.statusBar().showMessage(str(exc))
            event.ignore()
