from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QMessageBox, QTableWidget, QCheckBox
from abscada.security import UserStore, default_security, users_path
from test_operational_ui import operational_project, operational_studio, pump_until


def secure(window, **policy):
    window.project.security = dict(default_security(), enabled=True, **policy)
    store = UserStore(users_path(window.project.root))
    store.create("ana", "operar-la-planta", ["operator"], window.project.security, must_change=False)
    store.create("vera", "solo-mirar-123", ["viewer"], window.project.security, must_change=False)
    store.create("nuevo", "temporal-12345", ["operator"], window.project.security)
    window.project.screens["main"]["elements"] = [
        dict(id="set", kind="button", x=20, y=20, w=160, h=40, text="Nivel 50", action="set", tag="Level", value=50.0)]
    window.project.validate(); window.render_scene()
    return store


def fill_login(user, password, new_password=None):
    def fill():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QLineEdit, "login_user").setText(user)
        dialog.findChild(QLineEdit, "login_password").setText(password)
        if new_password:
            def change():
                second = QApplication.activeModalWidget()
                second.findChild(QLineEdit, "new_password").setText(new_password)
                second.findChild(QLineEdit, "repeat_password").setText(new_password)
                second.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
            QTimer.singleShot(50, change)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
    QTimer.singleShot(0, fill)


def silence_warnings(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[-1]))
    return shown


def test_command_asks_for_login_and_runs_with_operator(operational_studio, monkeypatch):
    window = operational_studio
    secure(window)
    window.start_runtime()
    root = window.runtime_window
    assert root.session_label.text().startswith("Sin sesión")
    element = root.project.screens["main"]["elements"][0]
    fill_login("ana", "operar-la-planta")
    root.actuate(element)
    pump_until(lambda: root.samples["Level"].value == 50.0)
    assert root.runtime.session.user == "ana" and root.session_label.text() == "Usuario: ana"
    assert root.session_button.text() == "Cerrar sesión"
    root.session_button.click()
    assert root.runtime.session is None


def test_viewer_role_is_refused_and_value_unchanged(operational_studio, monkeypatch):
    window = operational_studio
    secure(window)
    window.start_runtime()
    root = window.runtime_window
    shown = silence_warnings(monkeypatch)
    fill_login("vera", "solo-mirar-123")
    root.actuate(root.project.screens["main"]["elements"][0])
    assert shown and "no tiene el permiso" in shown[-1]
    assert root.runtime.snapshot()["Level"].value == 0.0


def test_first_login_requires_new_password(operational_studio, monkeypatch):
    window = operational_studio
    store = secure(window)
    window.start_runtime()
    root = window.runtime_window
    fill_login("nuevo", "temporal-12345", new_password="mi-clave-nueva-1")
    root.session_button.click()
    assert root.runtime.session.user == "nuevo" and not root.runtime.session.must_change
    assert store.authenticate("nuevo", "mi-clave-nueva-1", window.project.security)["must_change"] is False


def test_inactivity_logs_out(operational_studio):
    window = operational_studio
    secure(window, session_timeout_minutes=1)
    window.start_runtime()
    root = window.runtime_window
    root.runtime.login("ana", "operar-la-planta")
    root.runtime.session.last_activity -= 120
    pump_until(lambda: root.runtime.session is None)
    assert root.session_label.text().startswith("Sin sesión")


def test_studio_dialog_requires_an_administrator_before_enabling(operational_studio):
    from abscada.security_editor import edit_security
    window = operational_studio
    store = UserStore(users_path(window.project.root))
    messages = []

    def enable_without_admin():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QCheckBox, "security_enabled").setChecked(True)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        messages.append(dialog.validation_error.text())
        dialog.reject()
    QTimer.singleShot(0, enable_without_admin)
    edit_security(window)
    assert "al menos un usuario" in messages[0] and not window.project.security["enabled"]
    store.create("jefe", "gestionar-planta-1", ["supervisor"], window.project.security, must_change=False)

    def enable():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QCheckBox, "security_enabled").setChecked(True)
        assert dialog.findChild(QTableWidget, "accounts_table").rowCount() == 1
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(0, enable)
    edit_security(window)
    assert window.project.security["enabled"]
    window.save_project()
    assert (window.project.root / "security.json").exists()
    window.undo()
    assert not window.project.security["enabled"]
