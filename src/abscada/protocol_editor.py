"""Qt form generated from protocol metadata; never imports a client library."""
from PySide6.QtWidgets import QWidget, QFormLayout, QSpinBox, QLineEdit, QComboBox


class ProtocolForm(QWidget):
    def __init__(self, fields, values=None, kind=None, parent=None):
        super().__init__(parent)
        values = values or {}
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.controls = {}
        for field in fields:
            value = values.get(field.key, field.default)
            if field.choices:
                control = QComboBox()
                for key, title in field.options(kind):
                    control.addItem(title, key)
                control.setCurrentIndex(max(0, control.findData(value)))
            elif isinstance(field.default, int):
                control = QSpinBox()
                control.setRange(field.minimum, field.maximum)
                control.setValue(value)
            else:
                control = QLineEdit(str(value))
            control.setObjectName("protocol_" + field.key)
            self.controls[field.key] = control
            layout.addRow(field.label, control)

    def values(self):
        return {key: control.currentData() if isinstance(control, QComboBox)
                else control.value() if isinstance(control, QSpinBox)
                else control.text().strip() for key, control in self.controls.items()}


class BindingEditor(QWidget):
    """Keep a separate draft for each connection, including when switching protocols."""
    def __init__(self, connection, configs, kind, binding=None, parent=None):
        super().__init__(parent)
        self.connection, self.configs, self.kind = connection, configs, kind
        self.drafts = {}
        self.active = None
        self.form = None
        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        if binding:
            self.drafts[binding["connection"]] = binding["address"]
        connection.currentIndexChanged.connect(self.rebuild)
        self.rebuild()

    def rebuild(self, *args):
        from .connectors import definition
        for index in range(1, self.connection.count()):
            cid = self.connection.itemData(index)
            self.connection.model().item(index).setEnabled(
                definition(self.configs[cid]["protocol"]).supports_type(self.kind))
        if self.connection.currentIndex() > 0 and not self.connection.model().item(self.connection.currentIndex()).isEnabled():
            self.connection.setCurrentIndex(0)
            return
        if self.form:
            self.drafts[self.active] = self.form.values()
            self.layout.removeWidget(self.form)
            self.form.setParent(None)
            self.form.deleteLater()
            self.form = None
        self.active = self.connection.currentData()
        if self.active and self.kind in {"bool", "int", "float", "string"}:
            spec = definition(self.configs[self.active]["protocol"])
            data = self.drafts.get(self.active, {})
            data = spec.normalize(data, self.kind)
            self.form = ProtocolForm(spec.fields_for(self.kind), data, self.kind)
            self.layout.addRow(self.form)
        self.setVisible(self.form is not None)

    def binding(self):
        if not self.form:
            return None
        from .connectors import definition
        return dict(connection=self.active, version=definition(self.configs[self.active]["protocol"]).version,
                    address=self.form.values())
