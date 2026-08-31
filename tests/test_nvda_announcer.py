from __future__ import annotations

from unittest.mock import Mock, patch

from ui.nvda_announcer import speak_with_accessible_output


def test_accessible_output_speaks_and_interrupts_previous_announcement():
    output = Mock()
    output.is_active.return_value = True

    with patch("ui.nvda_announcer._accessible_output_nvda", return_value=output):
        assert speak_with_accessible_output("Descrição completa") is True

    output.speak.assert_called_once_with("Descrição completa", interrupt=True)


def test_accessible_output_falls_back_when_nvda_is_not_active():
    output = Mock()
    output.is_active.return_value = False

    with patch("ui.nvda_announcer._accessible_output_nvda", return_value=output):
        assert speak_with_accessible_output("Descrição completa") is False

    output.speak.assert_not_called()
