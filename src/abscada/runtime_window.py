"""Runtime windows share one acquisition service and frozen project snapshot."""
from __future__ import annotations
import copy
import time
from PySide6.QtCore import QTimer, Signal, Qt, QEvent, QPoint, QSettings
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtWidgets import QMainWindow, QInputDialog, QMessageBox, QLabel
from .theme import STYLE, configure_fonts
from .graphics import CanvasScene, CanvasView, ElementItem
from .runtime import Runtime
from .viewers import AlarmViewer, TrendViewer
from .operation_windows import MAIN_MODE, popup_key, popup_title, settings_key
from .i18n import tr, tr_existing
from . import button_actions
from .button_actions import SEQUENCE, STEP_ACTIONS
from .runtime_language_ui import runtime_ui


# Around the page when the window has other proportions than the screen (letterbox).
LETTERBOX = "#1b232d"
NOTICE_STYLE = ("QLabel { background: rgba(27, 35, 45, 225); color: white; border-radius: 4px;"
                " padding: 6px 10px; }")


def monitors():
    """Operator numbering: monitor 1 is the left-most screen, then top to bottom."""
    return sorted(QGuiApplication.screens(), key=lambda s: (s.geometry().x(), s.geometry().y()))


@runtime_ui
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
        self.scene.setBackgroundBrush(QColor(LETTERBOX))
        # Full screen hides the status bar; its messages float over the bottom of the screen.
        self.notice = QLabel(self.view)
        self.notice.setObjectName("fullscreenNotice")
        self.notice.setStyleSheet(NOTICE_STYLE)
        self.notice.setWordWrap(True)
        self.notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.notice.hide()
        self.statusBar().messageChanged.connect(self.show_notice)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        from PySide6.QtWidgets import QComboBox
        from .project_languages import languages
        self.language_selector = QComboBox()
        self.language_selector.setObjectName('runtimeLanguage')
        self.language_selector.addItems(languages(self.project))
        self.language_selector.setCurrentText(self.runtime.language)
        self.language_selector.setToolTip(tr('Cambiar idioma'))
        self.language_selector.currentTextChanged.connect(self.runtime.set_language)
        if len(languages(self.project)) > 1:
            self.statusBar().addPermanentWidget(self.language_selector)
        self.session_label = self.session_button = None
        if not owner and self.runtime.security.enabled:
            from PySide6.QtWidgets import QPushButton
            self.session_label = QLabel(); self.session_label.setObjectName("session_label")
            self.session_button = QPushButton(); self.session_button.setObjectName("session_button")
            self.session_button.clicked.connect(self.toggle_session)
            self.statusBar().addPermanentWidget(self.session_label)
            self.statusBar().addPermanentWidget(self.session_button)
            self.update_session_widgets()
        self.render_scene()
        self.displayed_language = self.runtime.language

    # -- operator session (root window only; pop-ups share it) --------------
    def update_session_widgets(self):
        if self.session_label is None:
            return
        session = self.runtime.session
        self.session_label.setText(tr("Usuario: {user}", user=session.display) if session else tr("Sin sesión · solo lectura"))
        self.session_button.setText(tr("Cerrar sesión") if session else tr("Iniciar sesión"))

    def toggle_session(self):
        if self.runtime.session:
            self.runtime.logout()
            self.statusBar().showMessage(tr("Sesión cerrada"), 5000)
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
            raise PermissionError(tr("El usuario {user} no tiene el permiso «{permissions_permissi}»", user=self.runtime.session.user, permissions_permissi=tr_existing(PERMISSIONS[permission])))
        if not self.request_login(tr("Esta orden necesita el permiso «{permissions_permissi}».", permissions_permissi=tr_existing(PERMISSIONS[permission]))):
            return False
        if not security.permits(self.runtime.session, permission):
            raise PermissionError(tr("El usuario {user} no tiene el permiso «{permissions_permissi}»", user=self.runtime.session.user, permissions_permissi=tr_existing(PERMISSIONS[permission])))
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
            if container.document_name:
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

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.update_chrome()

    def update_chrome(self):
        """Full screen gives the whole monitor to the screen. The status bar stays only
        when it holds the operator session controls, which have no other place."""
        self.statusBar().setHidden(self.isFullScreen() and self.session_label is None)
        self.show_notice(self.statusBar().currentMessage())

    def show_notice(self, text):
        if not text or not self.statusBar().isHidden():
            self.notice.hide()
            return
        self.notice.setText(text)
        self.place_notice()
        self.notice.show()
        self.notice.raise_()

    def place_notice(self):
        margin = 12
        text_width = self.notice.fontMetrics().horizontalAdvance(self.notice.text()) + 24
        self.notice.setFixedWidth(min(text_width, max(120, self.view.width() - 2 * margin)))
        self.notice.setFixedHeight(self.notice.heightForWidth(self.notice.width()))
        self.notice.move(margin, self.view.height() - self.notice.height() - margin)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.notice.isVisible():
            self.place_notice()

    def monitor(self, number):
        if number is None:
            return None
        screens = monitors()
        if number <= len(screens):
            return screens[number - 1]
        self.diagnostic.emit(tr("Monitor {number} no disponible; se usa el principal", number=number))
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
            raise ValueError(tr("Pantalla emergente inexistente"))
        return root.present(screen, dict(screen=screen), modal, window)

    def open_faceplate(self, template, bindings, title="", modal=False, window=None):
        """Faceplate of one equipment in its own window; each equipment gets its own."""
        root = self.owner or self
        if template not in root.project.faceplates:
            raise ValueError(tr("Objeto de librería emergente inexistente"))
        bindings = dict(bindings)
        target = dict(faceplate=dict(template=template, bindings=bindings,
                                     title=title))
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
        title = popup_title(self.project, self.faceplate['template'], self.faceplate['bindings'],
                            self.faceplate['title'], language=self.runtime.language)
        return dict(title=title, width=template["width"], height=template["height"],
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
        from .project_languages import resolve, default_language
        title = resolve(document.get('title', ''), self.runtime.language, default_language(self.project)) or self.document_name
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
        if self.displayed_language != self.runtime.language:
            self.displayed_language = self.runtime.language
            self.language_selector.blockSignals(True)
            self.language_selector.setCurrentText(self.runtime.language)
            self.language_selector.blockSignals(False)
            from .project_languages import resolve, default_language
            title = resolve(self.screen_document().get('title', ''), self.runtime.language, default_language(self.project)) or self.document_name
            self.setWindowTitle(title if self.owner else 'abSCADA Runtime · ' + self.project.manifest['name'] + ' · ' + title)
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
                    detail = result['message'].strip().splitlines() or [tr('Error de ejecución')]
                    text = tr("Script {script}: {detail}", script=result['script'], detail=detail[-1])
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
            self.statusBar().showMessage(tr("Sesión cerrada por inactividad"), 15000)
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
                raise ValueError(tr("El contenedor {target} no está en esta ventana", target=target))
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
                message=tr("Liberación no confirmada por el transporte: {name}. {exc}", name=name, exc=exc)
                self.diagnostic.emit(message);self.statusBar().showMessage(message,15000)
        self.release_futures=pending

    def event(self,event):
        if event.type()==QEvent.Type.WindowDeactivate and hasattr(self,'momentary'):
            self.release_momentaries()
        return super().event(event)

    def actuate(self, element, entry=False, source=None, phase=None, editor=None, text=None):
        """``entry``: an input box. With ``editor`` (the item) the value is typed in place and comes back in
        ``text``; without it a dialog asks for the value."""
        try:
            if element.get('action') in {'momentary','press_release'} and phase=='release':
                if id(element) in self.momentary:
                    self.momentary.pop(id(element))
                    try:
                        tag=self.runtime.tags[element['tag']]
                        if tag.get('binding') and self.runtime.snapshot()[element['tag']].quality!='good':
                            raise ValueError(tr('Sin comunicación; liberación no enviada'))
                        # Releases are never refused: a pressed command must always be able to stop.
                        future=self.runtime.write(element['tag'],element.get('release_value',False),
                                                  actor=self.runtime.security.actor(self.runtime.session),origin='hmi')
                        self.release_futures.append((element['tag'],future))
                    except Exception as exc:
                        message=tr("No se pudo enviar la liberación de {tag}: {exc}", tag=element['tag'], exc=exc)
                        self.diagnostic.emit(message); self.statusBar().showMessage(message,15000)
                return
            from .dynamics import permitted
            samples=self.runtime.snapshot()
            if not permitted(element,samples,'visible') or not permitted(element,samples,'enabled'):
                from .project_languages import resolve, default_language
                raise ValueError(resolve(element.get('dynamics',{}).get('disabled_reason',tr('No se cumple el permiso de operación')), self.runtime.language, default_language(self.project)))
            if phase == 'press':
                # No modal dialog while the mouse holds a momentary button: just refuse.
                from .security import required_permission
                if not self.runtime.security.permits(self.runtime.session, required_permission(element)):
                    (self.owner or self).statusBar().showMessage(tr("Inicia sesión con un usuario autorizado para usar este pulsador"), 8000)
                    return
            elif not self.authorize(element):
                return
            action = element.get("action", "toggle")
            if action == SEQUENCE:
                self.run_sequence(element, source)
                return
            if not entry and action in STEP_ACTIONS:
                self.click_action(element, source)()
                return
            if action in {'momentary', 'press_release'} and not element.get('tag'):
                raise ValueError(tr("Este mando no tiene variable asignada"))
            name, sample = self.command_target(element)
            if entry and text is not None:
                value = text
            elif entry and editor is not None:
                editor(str(sample.value), lambda typed: self.actuate(element, entry=True, source=source, text=typed))
                return
            elif entry:
                value, ok = QInputDialog.getText(self, tr("Escribir valor"), name, text=str(sample.value))
                if not ok:
                    return
            elif action in {'momentary','press_release'}:
                if phase!='press': return
                value=element.get('press_value',True)
            else:
                raise ValueError(tr("Acción de botón desconocida"))
            if entry:
                from .value_editor import engineering_value
                value=engineering_value(value,self.runtime.tags[name]['type'])
            self.runtime.command(name, value, self.runtime.session)
            if element.get('action') in {'momentary','press_release'}: self.momentary[id(element)]=element
        except Exception as exc:
            QMessageBox.warning(self, tr("Operación no realizada"), str(exc))

    def command_target(self, element):
        """Variable of a control and its sample; refuses one without a valid reading."""
        name = element.get("tag", "")
        if name not in self.runtime.tags:
            raise ValueError(tr("Este control no tiene una variable configurada"))
        sample = self.runtime.snapshot()[name]
        if self.runtime.tags[name].get("binding") and sample.quality != "good":
            raise ValueError(tr("La variable no tiene una lectura válida"))
        return name, sample

    def click_action(self, element, source):
        """Check a click action and return the function that performs it; nothing is sent yet."""
        action = element.get("action", "toggle")
        if action in {'toggle', 'set'} and not element.get('tag'):
            raise ValueError(tr("Este mando no tiene variable asignada"))
        if action == 'faceplate_popup' and '' in element.get('bindings', {}).values():
            raise ValueError(tr("El objeto emergente tiene parámetros sin variable asignada"))
        if action == 'set_language':
            return lambda: self.runtime.set_language(element['language'])
        if action == 'script':
            if element.get('script') not in self.project.scripts:
                raise ValueError(tr('Script inexistente'))
            screen = source.document_name if source else self.document_name
            return lambda: self.runtime.scripts.submit(element['script'], 'button', screen)
        if action in {"screen", "popup"}:
            target = element.get("screen", "")
            if target not in self.project.screens:
                raise ValueError(tr("Pantalla inexistente"))
            if action == "popup":
                return lambda: self.defer(lambda: self.open_popup(target, element.get("modal", False), element.get("window")))
            container = element.get('target_container', '')
            def navigate():
                try:
                    self.navigate_screen(target, container, source)
                except (ValueError, RuntimeError) as exc:
                    self.statusBar().showMessage(str(exc), 10000)
            return lambda: self.defer(navigate)
        if action == "faceplate_popup":
            template, bindings = element["template"], dict(element.get("bindings", {}))
            title, modal, window = element.get("title", ""), element.get("modal", False), element.get("window")
            return lambda: self.defer(lambda: self.open_faceplate(template, bindings, title, modal, window))
        if action == "close_popup":
            return lambda: self.defer(self.close) if self.owner else None
        name, sample = self.command_target(element)
        if action == "toggle":
            if self.runtime.tags[name]["type"] != "bool":
                raise ValueError(tr("La acción alternar necesita una variable bool"))
            value = not sample.value
        elif action == "set":
            value = element["value"]
        else:
            raise ValueError(tr("Acción de botón desconocida"))
        return lambda: self.runtime.command(name, value, self.runtime.session)

    def run_sequence(self, element, source):
        """Check every step before sending any; then send them in order without waiting.

        A failure while sending stops the rest; earlier steps were already sent and are not undone.
        """
        steps = [(number, step, button_actions.as_button(element, step))
                 for number, step in enumerate(button_actions.steps(element), 1)]
        prepared = []
        for number, step, button in steps:
            try:
                prepared.append((number, step, self.click_action(button, source)))
            except Exception as exc:
                raise ValueError(tr("Acción {number} ({label}): {exc}\nNo se ha enviado ninguna acción.",
                                    number=number, label=button_actions.label(step), exc=exc)) from exc
        for number, step, perform in prepared:
            try:
                perform()
            except Exception as exc:
                raise ValueError(tr("Acción {number} ({label}) no realizada: {exc}\nLas acciones anteriores ya se enviaron y no se deshacen; las siguientes no se han enviado.",
                                    number=number, label=button_actions.label(step), exc=exc)) from exc

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
