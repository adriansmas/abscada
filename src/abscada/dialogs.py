"""Release modal editor dialogs after callers have read their result fields."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit
from .i18n import tr


class EditorDialog(QDialog):
    validator = None

    def accept(self):
        try:
            if self.validator:
                self.validator()
        except (ValueError, TypeError, KeyError, OSError) as exc:
            if not hasattr(self, 'validation_error'):
                self.validation_error = QLabel(self)
                self.validation_error.setWordWrap(True)
                self.validation_error.setStyleSheet('color: #ad3030;')
                self.layout().addWidget(self.validation_error)
            self.validation_error.setText(str(exc))
            field = getattr(exc, 'field', None) or self.focusWidget() or self.findChild(QLineEdit)
            if field:
                field.setFocus()
            return
        super().accept()

    def exec(self):
        for box in self.findChildren(QDialogButtonBox):
            for key, title in ((QDialogButtonBox.StandardButton.Cancel, tr('Cancelar')),
                               (QDialogButtonBox.StandardButton.Save, tr('Aceptar')),
                               (QDialogButtonBox.StandardButton.Ok, tr('Aceptar')),
                               (QDialogButtonBox.StandardButton.Close, tr('Cerrar'))):
                if box.button(key): box.button(key).setText(title)
        try:
            return super().exec()
        finally:
            # Unlike WA_DeleteOnClose, this leaves fields available immediately
            # after exec() while preventing parent-owned dialogs accumulating.
            self.deleteLater()
