"""Operator login and first-login password change for the runtime."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout
from .i18n import tr


class LoginDialog(QDialog):
    def __init__(self, runtime, parent=None, reason=""):
        super().__init__(parent)
        self.runtime, self.session = runtime, None
        self.setWindowTitle(tr("Iniciar sesión"))
        layout = QVBoxLayout(self)
        if reason:
            note = QLabel(reason); note.setWordWrap(True); layout.addWidget(note)
        form = QFormLayout(); layout.addLayout(form)
        self.user = QLineEdit(); self.user.setObjectName("login_user")
        self.password = QLineEdit(); self.password.setObjectName("login_password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr("Usuario"), self.user); form.addRow(tr("Contraseña"), self.password)
        self.error = QLabel(); self.error.setStyleSheet("color: #ad3030;"); self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Iniciar sesión"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancelar"))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            session = self.runtime.login(self.user.text().strip(), self.password.text())
        except PermissionError as exc:
            self.error.setText(str(exc)); self.password.clear(); self.password.setFocus()
            return
        finally:
            self.password.clear()
        if session.must_change:
            change = ChangePasswordDialog(self.runtime, session, self)
            if change.exec() != QDialog.DialogCode.Accepted:
                self.runtime.logout()
                self.error.setText(tr("Debes cambiar la contraseña para continuar"))
                return
        self.session = session
        super().accept()


class ChangePasswordDialog(QDialog):
    def __init__(self, runtime, session, parent=None):
        super().__init__(parent)
        self.runtime, self.session = runtime, session
        self.setWindowTitle(tr("Cambiar contraseña"))
        layout = QVBoxLayout(self)
        policy = runtime.security.policy
        layout.addWidget(QLabel(tr("Primer acceso de {user}: elige una contraseña propia (mínimo {password_min_length} caracteres).", user=session.user, password_min_length=policy['password_min_length'])))
        form = QFormLayout(); layout.addLayout(form)
        self.first, self.second = QLineEdit(), QLineEdit()
        for field, name in ((self.first, "new_password"), (self.second, "repeat_password")):
            field.setEchoMode(QLineEdit.EchoMode.Password); field.setObjectName(name)
        form.addRow(tr("Nueva contraseña"), self.first); form.addRow(tr("Repetir"), self.second)
        self.error = QLabel(); self.error.setStyleSheet("color: #ad3030;"); self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Guardar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancelar"))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if self.first.text() != self.second.text():
            self.error.setText(tr("Las contraseñas no coinciden"))
            return
        security = self.runtime.security
        try:
            security.store.set_password(self.session.user, self.first.text(), security.policy)
        except (ValueError, KeyError) as exc:
            self.error.setText(str(exc))
            return
        finally:
            self.first.clear(); self.second.clear()
        self.session.must_change = False
        self.runtime.audit("password_changed", self.session.user, self.session)
        super().accept()
