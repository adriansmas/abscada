"""Scope runtime UI translations without changing the language of Studio."""
from functools import wraps
import inspect
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QAbstractButton, QComboBox, QTableWidget
from .i18n import using_language, load_catalog, tr, language
from .project_languages import default_language

SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 101


def chrome_sources(widget, code):
    catalog = load_catalog(code)
    reverse = {v: k for k, v in catalog.items()}
    # Imported captions may already have been translated in Studio.
    reverse.update({v: k for k, v in load_catalog(language()).items()})
    known = set(load_catalog('en'))
    def source(text):
        original = reverse.get(text, text)
        return original if original in known else None
    for child in widget.findChildren(QLabel) + widget.findChildren(QAbstractButton):
        original = source(child.text())
        if original:
            child.setProperty('runtimeTextSource', original)
    for child in widget.findChildren(QComboBox):
        for index in range(child.count()):
            original = source(child.itemText(index))
            if original:
                child.setItemData(index, original, SOURCE_ROLE)
    for child in widget.findChildren(QTableWidget):
        for column in range(child.columnCount()):
            item = child.horizontalHeaderItem(column)
            if item:
                original = source(item.text())
                if original:
                    item.setData(SOURCE_ROLE, original)


def translate_chrome(widget):
    for child in widget.findChildren(QLabel) + widget.findChildren(QAbstractButton):
        source = child.property('runtimeTextSource')
        if source:
            child.setText(tr(source))
    for child in widget.findChildren(QComboBox):
        for index in range(child.count()):
            source = child.itemData(index, SOURCE_ROLE)
            if source:
                child.setItemText(index, tr(source))
    for child in widget.findChildren(QTableWidget):
        for column in range(child.columnCount()):
            item = child.horizontalHeaderItem(column)
            if item and item.data(SOURCE_ROLE):
                item.setText(tr(item.data(SOURCE_ROLE)))


def runtime_ui(cls):
    """All authored Qt callbacks use their shared Runtime's language."""
    def wrap(method):
        signature = inspect.signature(method)
        @wraps(method)
        def callback(self, *args, **kwargs):
            runtime = getattr(self, 'runtime', None)
            if runtime is None and method.__name__ == '__init__':
                bound = signature.bind(self, *args, **kwargs).arguments
                runtime = bound.get('runtime') or getattr(bound.get('owner'), 'runtime', None)
                project = bound.get('project') or getattr(runtime, 'project', None)
            else:
                project = getattr(self, 'project', None) or getattr(runtime, 'project', None)
            code = getattr(runtime, 'language', None) or (default_language(project) if project else language())
            with using_language(code):
                if method.__name__ != '__init__' and getattr(self, '_chrome_language', code) != code:
                    self._chrome_language = code
                    translate_chrome(self)
                result = method(self, *args, **kwargs)
                if method.__name__ == '__init__':
                    code = getattr(getattr(self, 'runtime', None), 'language', code)
                    chrome_sources(self, code)
                    self._chrome_language = code
                    with using_language(code):
                        translate_chrome(self)
                return result
        return callback
    for name, member in list(vars(cls).items()):
        if inspect.isfunction(member):
            setattr(cls, name, wrap(member))
    return cls
