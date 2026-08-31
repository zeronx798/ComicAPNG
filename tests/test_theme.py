"""Tests for centralized dark-theme surface rules."""

from comicapng.ui.theme import application_stylesheet


def test_plain_text_widgets_are_transparent() -> None:
    stylesheet = application_stylesheet()
    assert "QLabel {" in stylesheet
    assert "background-color: transparent;" in stylesheet
    assert "QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled" in stylesheet


def test_global_widget_rule_does_not_paint_child_backgrounds() -> None:
    stylesheet = application_stylesheet()
    widget_rule = stylesheet.split("QWidget {", 1)[1].split("}", 1)[0]
    assert "background" not in widget_rule


def test_intentional_control_surfaces_remain_styled() -> None:
    stylesheet = application_stylesheet()
    assert "QPushButton, QToolButton" in stylesheet
    assert "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox" in stylesheet
    assert "QFrame#panel" in stylesheet
    assert "QProgressBar" in stylesheet
