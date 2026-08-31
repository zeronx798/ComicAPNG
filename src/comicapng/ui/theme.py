"""Centralized ComicAPNG dark theme."""

BACKGROUND = "#15181d"
SIDEBAR = "#1b2027"
SURFACE = "#20262e"
SURFACE_RAISED = "#28313b"
SELECTION = "#294e6f"
ACCENT = "#55a8e8"
TEXT = "#edf2f7"
TEXT_MUTED = "#a9b4c1"
BORDER = "#37414d"
DANGER = "#e06c75"


def application_stylesheet() -> str:
    return f"""
QWidget {{
    color: {TEXT};
    font-size: 10pt;
}}
QMainWindow, QDialog {{ background-color: {BACKGROUND}; }}
QLabel {{
    background-color: transparent;
    border: none;
}}
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{
    color: #697582;
}}
QGroupBox, QGroupBox::title {{ background-color: transparent; }}
QFrame#sidebar {{ background-color: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QFrame#panel {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 5px; }}
QLabel#muted {{ color: {TEXT_MUTED}; }}
QLabel#heading {{ font-size: 17pt; font-weight: 600; }}
QPushButton, QToolButton {{
    background-color: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-radius: 4px;
    min-height: 30px;
    padding: 4px 10px;
}}
QPushButton:hover, QToolButton:hover {{ background-color: #313c48; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {SELECTION}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #697582; background-color: {SURFACE}; }}
QToolButton:checked {{ background-color: {SELECTION}; border-color: {ACCENT}; }}
QPushButton#primary, QToolButton#primary {{ background-color: #24699a; border-color: #3186bd; font-weight: 600; }}
QPushButton#primary:hover, QToolButton#primary:hover {{ background-color: #2c7bb0; }}
QPushButton#primary:disabled, QToolButton#primary:disabled {{
    color: #697582;
    background-color: {SURFACE};
    border-color: {BORDER};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget, QListWidget, QPlainTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    selection-background-color: {SELECTION};
    padding: 4px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTableWidget:focus, QListWidget:focus {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {SELECTION};
}}
QListWidget::item {{ border-radius: 4px; padding: 4px; }}
QListWidget::item:selected {{ background-color: {SELECTION}; }}
QListWidget::item:hover {{ background-color: {SURFACE_RAISED}; }}
QHeaderView::section {{ background-color: {SURFACE_RAISED}; padding: 6px; border: 0; border-right: 1px solid {BORDER}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background-color: {SURFACE}; padding: 8px 16px; }}
QTabBar::tab:selected {{ background-color: {SELECTION}; }}
QProgressBar {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px; text-align: center; }}
QProgressBar::chunk {{ background-color: {ACCENT}; }}
QMenuBar, QMenu, QStatusBar {{ background-color: {SIDEBAR}; }}
QMenu::item:selected {{ background-color: {SELECTION}; }}
QToolTip {{ background-color: {SURFACE_RAISED}; color: {TEXT}; border: 1px solid {BORDER}; }}
QScrollBar:vertical {{ background: {BACKGROUND}; width: 12px; }}
QScrollBar::handle:vertical {{ background: #485563; min-height: 30px; border-radius: 5px; }}
QScrollBar:horizontal {{ background: {BACKGROUND}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: #485563; min-width: 30px; border-radius: 5px; }}
"""
