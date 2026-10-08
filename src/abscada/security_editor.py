"""Studio dialogs: users and roles, OPC UA server, certificates and connection passwords.

Policy and roles are project data (undo, save, versions). Accounts, certificates and
passwords belong to this installation (``runtime/``): they change immediately and never
travel with the project.
"""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)
from .dialogs import EditorDialog
from .security import PERMISSIONS, UserStore, users_path
from .i18n import tr


def _spin(value, low, high):
    field = QSpinBox(); field.setRange(low, high); field.setValue(value)
    return field


def edit_security(studio):
    project = studio.project
    policy = copy.deepcopy(project.security)
    dialog = EditorDialog(studio); dialog.setWindowTitle(tr("Usuarios y roles")); dialog.resize(1080, 560)
    layout = QVBoxLayout(dialog)
    tabs = QTabWidget(); layout.addWidget(tabs)

    # -- policy -------------------------------------------------------------
    page = QWidget(); form = QFormLayout(page)
    enabled = QCheckBox(tr("Exigir inicio de sesión en el runtime")); enabled.setObjectName("security_enabled")
    enabled.setChecked(policy["enabled"])
    timeout = _spin(policy["session_timeout_minutes"], 0, 1440)
    length = _spin(policy["password_min_length"], 8, 128)
    failures = _spin(policy["max_failed_logins"], 1, 100)
    lockout = _spin(policy["lockout_minutes"], 1, 1440)
    form.addRow(enabled)
    form.addRow(tr("Cierre por inactividad (min, 0 = nunca)"), timeout)
    form.addRow(tr("Longitud mínima de contraseña"), length)
    form.addRow(tr("Intentos fallidos antes de bloquear"), failures)
    form.addRow(tr("Duración del bloqueo (min)"), lockout)
    note = QLabel(tr("Sin seguridad, cualquiera puede operar desde el runtime (comportamiento anterior). "
                  "Con seguridad, el runtime arranca sin sesión y en solo lectura; mandos, consignas, scripts "
                  "y reconocimientos piden un usuario con permiso, y quedan auditados con su nombre."))
    note.setWordWrap(True); form.addRow(note)
    tabs.addTab(page, tr("Política"))

    # -- roles --------------------------------------------------------------
    page = QWidget(); box = QVBoxLayout(page)
    roles = QTableWidget(0, 2 + len(PERMISSIONS)); roles.setObjectName("roles_table")
    roles.setHorizontalHeaderLabels([tr("Identificador"), tr("Nombre")] + list(PERMISSIONS.values()))
    # Permission names are long: show them whole (one per column) and let the table scroll.
    header = roles.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    for column, title in enumerate(PERMISSIONS.values(), 2):
        roles.horizontalHeaderItem(column).setToolTip(title)
    box.addWidget(roles)

    def add_role(role=None):
        role = role or dict(id="", name="", permissions=[])
        row = roles.rowCount(); roles.insertRow(row)
        roles.setItem(row, 0, QTableWidgetItem(role["id"])); roles.setItem(row, 1, QTableWidgetItem(role["name"]))
        for column, key in enumerate(PERMISSIONS, 2):
            item = QTableWidgetItem(); item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(Qt.CheckState.Checked if key in role["permissions"] else Qt.CheckState.Unchecked)
            roles.setItem(row, column, item)
    for role in policy["roles"]:
        add_role(role)
    row = QHBoxLayout(); box.addLayout(row)
    for title, callback in ((tr("Añadir rol"), lambda: add_role()), (tr("Eliminar rol"), lambda: roles.removeRow(roles.currentRow()))):
        button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
    row.addStretch()
    tabs.addTab(page, tr("Roles"))

    # -- accounts (saved with the project, written at once) ------------------
    store = UserStore(users_path(project.root))
    page = QWidget(); box = QVBoxLayout(page)
    info = QLabel(tr("Cuentas del proyecto, en users.json: viajan con él. Solo se guarda la huella de cada contraseña "
                  "(scrypt). Los cambios se graban al momento, sin pulsar Guardar."))
    info.setWordWrap(True); box.addWidget(info)
    accounts = QTableWidget(0, 4); accounts.setObjectName("accounts_table")
    accounts.setHorizontalHeaderLabels([tr("Usuario"), tr("Nombre"), tr("Roles"), tr("Estado")])
    accounts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    accounts.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    accounts.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    box.addWidget(accounts)
    feedback = QLabel(); feedback.setWordWrap(True); box.addWidget(feedback)

    def refresh_accounts():
        users = store.users()
        accounts.setRowCount(len(users))
        for i, user in enumerate(users):
            state = tr("Desactivado") if user.get("disabled") else tr("Cambiar contraseña al entrar") if user.get("must_change") else tr("Activo")
            for column, text in enumerate((user["name"], user.get("full_name", ""), ", ".join(user["roles"]), state)):
                accounts.setItem(i, column, QTableWidgetItem(text))

    def current_policy():
        return dict(policy, roles=read_roles(), password_min_length=length.value(),
                    max_failed_logins=failures.value(), lockout_minutes=lockout.value())

    def selected():
        row = accounts.currentRow()
        return accounts.item(row, 0).text() if row >= 0 and accounts.item(row, 0) else None

    def run(action):
        try:
            action(); feedback.setText(""); refresh_accounts()
        except (ValueError, KeyError) as exc:
            feedback.setText(str(exc))

    def new_account():
        form = AccountDialog(dialog, current_policy())
        if form.exec() == QDialog.DialogCode.Accepted:
            run(lambda: store.create(form.name.text().strip(), form.password.text(), form.roles(), current_policy(),
                                     form.full_name.text().strip(), form.must_change.isChecked()))

    def reset_password():
        name = selected()
        if name:
            form = AccountDialog(dialog, current_policy(), name=name, password_only=True)
            if form.exec() == QDialog.DialogCode.Accepted:
                run(lambda: store.set_password(name, form.password.text(), current_policy(), form.must_change.isChecked()))

    def change_roles():
        name = selected()
        if name:
            user = store.find(name)
            form = AccountDialog(dialog, current_policy(), name=name, roles_only=True, current=user["roles"])
            if form.exec() == QDialog.DialogCode.Accepted:
                run(lambda: store.set_roles(name, form.roles(), current_policy()))

    def change_language():
        name = selected()
        if not name:
            return
        codes = [''] + project.manifest.get('languages', ['es'])
        current = store.find(name).get('language', '')
        chosen, accepted = QInputDialog.getItem(dialog, tr('Idioma del usuario'), tr('Idioma (vacío: puesto)'), codes,
                                               codes.index(current) if current in codes else 0, False)
        if accepted:
            run(lambda: store.set_language(name, chosen, codes))

    def toggle_disabled():
        name = selected()
        if name:
            run(lambda: store.set_disabled(name, not store.find(name).get("disabled")))

    def delete():
        name = selected()
        if name and QMessageBox.question(dialog, tr("Eliminar usuario"), tr("¿Eliminar la cuenta {name}?", name=name)) == QMessageBox.StandardButton.Yes:
            run(lambda: store.delete(name))

    row = QHBoxLayout(); box.addLayout(row)
    for title, callback in ((tr("Nuevo usuario…"), new_account), (tr("Restablecer contraseña…"), reset_password),
                            (tr("Roles…"), change_roles), (tr("Idioma…"), change_language), (tr("Activar / desactivar"), toggle_disabled), (tr("Eliminar"), delete)):
        button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
    row.addStretch()
    tabs.addTab(page, tr("Cuentas"))
    refresh_accounts()

    def read_roles():
        result = []
        for r in range(roles.rowCount()):
            identifier = (roles.item(r, 0).text() if roles.item(r, 0) else "").strip()
            name = (roles.item(r, 1).text() if roles.item(r, 1) else "").strip()
            granted = [key for c, key in enumerate(PERMISSIONS, 2) if roles.item(r, c).checkState() == Qt.CheckState.Checked]
            result.append(dict(id=identifier, name=name, permissions=granted))
        return result

    def data():
        return dict(enabled=enabled.isChecked(), session_timeout_minutes=timeout.value(), password_min_length=length.value(),
                    max_failed_logins=failures.value(), lockout_minutes=lockout.value(), roles=read_roles())

    def validate():
        candidate = copy.deepcopy(project); candidate.security = data(); candidate.validate()
        if candidate.security["enabled"]:
            admins = [u for u in store.users() if not u.get("disabled") and
                      "manage_users" in {p for r in candidate.security["roles"] if r["id"] in u["roles"] for p in r["permissions"]}]
            if not store.users():
                raise ValueError(tr("Crea al menos un usuario en Cuentas antes de exigir inicio de sesión"))
            if not admins:
                raise ValueError(tr("Al menos una cuenta activa debe tener un rol con «Gestionar usuarios»"))
    dialog.validator = validate
    studio.dialog_buttons(dialog, layout)
    if dialog.exec() == EditorDialog.DialogCode.Accepted and data() != project.security:
        value = data()
        studio.mutate(lambda: setattr(project, "security", value))


class AccountDialog(QDialog):
    def __init__(self, parent, policy, name="", password_only=False, roles_only=False, current=()):
        super().__init__(parent)
        self.setWindowTitle(tr("Usuario"))
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        self.name = QLineEdit(name); self.name.setReadOnly(bool(name)); self.name.setObjectName("account_name")
        self.full_name = QLineEdit(); self.full_name.setObjectName("account_full_name")
        self.password, self.repeat = QLineEdit(), QLineEdit()
        for field, key in ((self.password, "account_password"), (self.repeat, "account_repeat")):
            field.setEchoMode(QLineEdit.EchoMode.Password); field.setObjectName(key)
        self.must_change = QCheckBox(tr("Pedir una contraseña nueva en el primer acceso")); self.must_change.setChecked(True)
        self.role_list = QListWidget(); self.role_list.setObjectName("account_roles")
        for role in policy["roles"]:
            item = QListWidgetItem(f"{role['name']} ({role['id']})"); item.setData(Qt.ItemDataRole.UserRole, role["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if role["id"] in current else Qt.CheckState.Unchecked)
            self.role_list.addItem(item)
        form.addRow(tr("Usuario"), self.name)
        if not password_only and not roles_only:
            form.addRow(tr("Nombre completo"), self.full_name)
        if not roles_only:
            form.addRow(tr("Contraseña"), self.password); form.addRow(tr("Repetir"), self.repeat); form.addRow(self.must_change)
            form.addRow(QLabel(tr("Mínimo {password_min_length} caracteres. La contraseña no se guarda: solo su huella (scrypt).", password_min_length=policy['password_min_length'])))
        if not password_only:
            form.addRow(tr("Roles"), self.role_list)
        self.roles_only, self.error = roles_only, QLabel()
        self.error.setStyleSheet("color: #ad3030;"); layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Aceptar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancelar"))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def roles(self):
        return [self.role_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.role_list.count())
                if self.role_list.item(i).checkState() == Qt.CheckState.Checked]

    def accept(self):
        if not self.roles_only and self.password.text() != self.repeat.text():
            self.error.setText(tr("Las contraseñas no coinciden")); return
        super().accept()


def edit_opcua_server(studio):
    from .opcua_server import SECURITY, endpoint
    project = studio.project
    config = copy.deepcopy(project.opcua_server)
    dialog = EditorDialog(studio); dialog.setWindowTitle(tr("Servidor OPC UA")); dialog.resize(560, 480)
    layout = QVBoxLayout(dialog); form = QFormLayout(); layout.addLayout(form)
    enabled = QCheckBox(tr("Publicar las variables por OPC UA mientras corre el runtime")); enabled.setChecked(config["enabled"])
    enabled.setObjectName("opcua_enabled")
    port = _spin(config["port"], 1, 65535); port.setObjectName("opcua_port")
    policies = QListWidget(); policies.setObjectName("opcua_policies")
    titles = {"None": tr("Sin seguridad (solo pruebas)"), "Basic256Sha256_Sign": "Basic256Sha256 · solo firma"}
    for key in SECURITY:
        item = QListWidgetItem(titles.get(key, key.rsplit("_", 1)[0].replace("_", "-") + tr(" · firma y cifrado")))
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if key in config["security"] else Qt.CheckState.Unchecked)
        policies.addItem(item)
    anonymous = QCheckBox(tr("Permitir lectura anónima (nunca escritura)")); anonymous.setChecked(config["allow_anonymous"])
    form.addRow(enabled); form.addRow(tr("Puerto TCP"), port); form.addRow(tr("Políticas"), policies); form.addRow(anonymous)
    help_text = QLabel(tr("Endpoint: {replace}. Los clientes inician sesión con cuentas de abSCADA cuyo rol tenga «Acceso por OPC UA»; para escribir también necesitan «Mandos y consignas». El certificado de cada cliente debe aceptarse en Certificados.", replace=endpoint(config).replace('0.0.0.0', '<IP de este equipo>')))
    help_text.setWordWrap(True); layout.addWidget(help_text)
    certificates = QPushButton(tr("Certificados…")); certificates.clicked.connect(lambda: certificates_dialog(studio))
    layout.addWidget(certificates)

    def data():
        return dict(enabled=enabled.isChecked(), port=port.value(), allow_anonymous=anonymous.isChecked(),
                    security=[policies.item(i).data(Qt.ItemDataRole.UserRole) for i in range(policies.count())
                              if policies.item(i).checkState() == Qt.CheckState.Checked])

    def validate():
        candidate = copy.deepcopy(project); candidate.opcua_server = data(); candidate.validate()
        if candidate.opcua_server["enabled"] and not candidate.security["enabled"] and not candidate.opcua_server["allow_anonymous"]:
            raise ValueError(tr("Sin usuarios activados nadie podría conectarse: activa la seguridad (Usuarios…) o la lectura anónima"))
    dialog.validator = validate
    studio.dialog_buttons(dialog, layout)
    if dialog.exec() == EditorDialog.DialogCode.Accepted and data() != project.opcua_server:
        value = data()
        studio.mutate(lambda: setattr(project, "opcua_server", value))


def certificates_dialog(studio):
    from . import pki
    root = studio.project.root
    dialog = QDialog(studio); dialog.setWindowTitle(tr("Certificados OPC UA de este equipo")); dialog.resize(760, 460)
    layout = QVBoxLayout(dialog)
    note = QLabel(tr("Rechazados: servidores o clientes que intentaron conectar y aún no son de confianza. Comprueba la "
                  "huella con el otro equipo antes de aceptar."))
    note.setWordWrap(True); layout.addWidget(note)
    lists = {}
    for name, title in (("rejected", tr("Rechazados")), ("trusted", tr("De confianza"))):
        layout.addWidget(QLabel(title))
        widget = QListWidget(); widget.setObjectName("certificates_" + name); lists[name] = widget; layout.addWidget(widget)

    def refresh():
        for name, widget in lists.items():
            widget.clear()
            for info in pki.listing(root, name):
                item = QListWidgetItem(tr("{subject} · {uri} · huella {fingerprint} · válido hasta {info_valid_until_10}", subject=info['subject'], uri=info['uri'], fingerprint=info['fingerprint'], info_valid_until_10=info['valid_until'][:10]))
                item.setData(Qt.ItemDataRole.UserRole, str(info["path"])); widget.addItem(item)

    def trust():
        item = lists["rejected"].currentItem()
        if item:
            from pathlib import Path
            pki.trust(root, Path(item.data(Qt.ItemDataRole.UserRole)).read_bytes()); refresh()

    def remove():
        item = lists["trusted"].currentItem()
        if item:
            from pathlib import Path
            Path(item.data(Qt.ItemDataRole.UserRole)).unlink(missing_ok=True); refresh()
    row = QHBoxLayout(); layout.addLayout(row)
    for title, callback in ((tr("Confiar en el seleccionado"), trust), (tr("Quitar confianza"), remove)):
        button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
    row.addStretch()
    close = QPushButton(tr("Cerrar")); close.clicked.connect(dialog.accept); row.addWidget(close)
    refresh()
    dialog.exec()


def set_connection_password(parent, project_root, connection_id):
    from .secrets_store import SecretStore, connection_secret_key, secrets_path
    if not connection_id:
        QMessageBox.information(parent, tr("Contraseña"), tr("Pon nombre a la conexión antes de guardar su contraseña"))
        return False
    password, ok = QInputDialog.getText(parent, tr("Contraseña de la conexión"),
                                        tr("Contraseña para {connection_id} (vacía = borrar). Se guarda al momento en el proyecto (secrets.json), codificada pero no cifrada.", connection_id=connection_id), QLineEdit.EchoMode.Password)
    if ok:
        SecretStore(secrets_path(project_root)).set(connection_secret_key(connection_id), password)
    return ok
