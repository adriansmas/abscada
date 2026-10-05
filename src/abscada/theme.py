"""Shared visual language for engineering and operation windows."""
from pathlib import Path
import os
import sys
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import QTranslator, QLibraryInfo
from PySide6.QtWidgets import QApplication


def configure_fonts():
    app=QApplication.instance()
    if app and not hasattr(app,'spanish_translator'):
        app.spanish_translator=QTranslator(app)
        if app.spanish_translator.load('qtbase_es',QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(app.spanish_translator)
    if not QFontDatabase.families():
        directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
            if (directory / filename).exists():
                QFontDatabase.addApplicationFont(str(directory / filename))
    return QFont("Segoe UI" if sys.platform == "win32" else "DejaVu Sans", 10)


STYLE = """
QWidget { color: #263449; font-size: 13px; }
QMainWindow, QDialog { background: #f3f5f8; }
QWidget#sidebar { background: #142237; }
QWidget#sidebar QLabel { color: #a5b4c8; }
QWidget#sidebar QLabel#brand { color: white; font-size: 24px; font-weight: 700; }
QLabel#pageTitle { font-size: 23px; font-weight: 700; color: #17273d; }
QLabel#sectionTitle { font-weight: 600; color: #506176; font-size: 11px; }
QLabel#muted { color: #738197; }
QLabel#designBadge { background: #e1eaf8; color: #315a92; border-radius: 5px; padding: 5px 10px; font-weight: 600; }
QLabel#runtimeBadge { background: #d9f5e8; color: #13714b; border-radius: 5px; padding: 5px 10px; font-weight: 600; }
QFrame#panel { background: white; border: 1px solid #dee5ed; border-radius: 7px; }
QWidget#inspector, QWidget#resources { background: white; }
QPushButton { background: white; border: 1px solid #d3dce7; padding: 7px 12px; border-radius: 5px; font-weight: 500; }
QPushButton:hover { background: #edf3fa; border-color: #a4b6ce; }
QPushButton:pressed { background: #dfe9f5; }
QPushButton:disabled { color: #99a4b2; background: #f5f7fa; border-color: #e5eaf0; }
QPushButton#primary { background: #147d75; border-color: #147d75; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #0f6963; }
QPushButton#danger { color: #b54747; }
QPushButton#nav { background: transparent; border: none; color: #b5c2d3; text-align: left; padding: 12px; border-radius: 5px; }
QPushButton#nav:checked { background: #293e59; color: white; }
QPushButton#nav:hover { background: #21344c; color: white; }
QPushButton#nav:disabled { color: #6e8099; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: white; border: 1px solid #d3dce7; border-radius: 4px; padding: 5px; min-height: 20px; selection-background-color: #d5e9f8; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #3b8fba; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e0edf8; selection-color: #17273d; }
QPlainTextEdit { background: white; border: 1px solid #dce3ec; padding: 6px; selection-background-color: #d5e9f8; }
QListWidget, QTreeWidget { background: white; border: none; outline: none; }
QListWidget::item, QTreeWidget::item { padding: 7px; border-radius: 4px; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #e4f1f5; color: #12696e; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #f1f5f9; }
QListWidget#toolbox::item { background: #f6f8fb; border: 1px solid #e0e7ef; padding: 9px; margin: 3px; }
QListWidget#toolbox::item:selected { background: #dff1f0; border-color: #65b1aa; }
QTableWidget { background: white; alternate-background-color: #f8fafc; border: 1px solid #e0e6ee; gridline-color: #edf1f6; selection-background-color: #e1eef8; selection-color: #1c3b59; outline: none; }
QHeaderView::section { background: #f4f7fa; color: #627289; border: none; border-bottom: 1px solid #dfe5ec; padding: 10px; font-weight: 600; }
QToolBar { background: white; border: none; border-bottom: 1px solid #dde4ed; spacing: 8px; padding: 9px; }
QToolButton { padding: 6px 10px; border-radius: 4px; }
QToolButton:hover { background: #eef3f8; }
QToolButton:checked { background: #e0edf8; }
QStatusBar { background: white; border-top: 1px solid #dfe5ed; color: #6c7c90; }
QSplitter::handle { background: #e4e9f0; width: 1px; }
QScrollArea { border: none; background: transparent; }
QGroupBox { font-weight: 600; border: 1px solid #e1e7ef; border-radius: 5px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QDialogButtonBox QPushButton { min-width: 70px; }
"""

STUDIO_STYLE = """
QListWidget#toolbox { font-size: 12px; }
QListWidget#toolbox::item { padding: 4px; margin: 2px; }
QLabel#pageTitle { font-size: 20px; }
QWidget#sidebar QLabel#brand { font-size: 21px; }
QPushButton#nav { padding: 8px; }
QToolBar { padding: 5px; spacing: 5px; }
QToolButton { padding: 4px 8px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 3px; min-height: 18px; }
QPushButton { padding: 5px 9px; }
QWidget#resources QPushButton { padding: 4px 5px; font-size: 12px; }
QGroupBox { margin-top: 9px; padding-top: 8px; }
"""

STUDIO_STYLE += """
QMainWindow { background: #e9edf2; }
QWidget#resources { border-right: 1px solid #d5dde6; background: #f8fafc; }
QLabel#projectName { font-size: 14px; font-weight: 600; color: #23374b; padding-bottom: 6px; }
QListWidget#toolbox { background: transparent; font-size: 11px; }
QListWidget#toolbox::item { background: transparent; border: 1px solid transparent; padding: 1px; margin: 1px; border-radius: 3px; }
QListWidget#toolbox::item:hover { background: #e8eef5; border-color: #d5e0eb; }
QListWidget#toolbox::item:selected { background: #dbeceb; border-color: #7faea9; }
QTreeWidget::item { padding: 5px 3px; border-radius: 2px; }
QTabWidget::pane { border: 1px solid #dae2eb; background: white; }
QTabBar::tab { background: #edf1f6; padding: 7px 12px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { background: white; border-bottom-color: #147d75; }
QLabel#pageTitle { font-size: 17px; }
QGroupBox { border-radius: 3px; }
"""
