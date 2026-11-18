from unittest.mock import Mock, patch
import pytest

from ui.app_frame import MainFrame


def test_on_live_chat_incoming_speaks_with_nvda():
    frame = Mock(_closing_app=False, _live_chat_messages=None, live_chat_list=None)
    with patch("ui.app_frame.speak_with_accessible_output", return_value=True) as mock_speak:
        MainFrame._on_live_chat_incoming(frame, "User1: Salve streamer!")
        mock_speak.assert_called_once_with("User1: Salve streamer!", interrupt=False)


def test_on_live_chat_incoming_falls_back_to_uia():
    frame = Mock(_closing_app=False, _live_chat_messages=None, live_chat_list=None)
    with patch("ui.app_frame.speak_with_accessible_output", return_value=False), \
         patch("ui.app_frame.speak_with_nvda", return_value=False), \
         patch("ui.app_frame.raise_uia_notification") as mock_uia:
        MainFrame._on_live_chat_incoming(frame, "User2: Muito bom!")
        mock_uia.assert_called_once_with(frame.status_field, "User2: Muito bom!")


def test_on_live_chat_incoming_appends_to_list_and_updates_details():
    chat_list = Mock()
    chat_list.GetSelection.return_value = 0
    details = Mock()
    frame = Mock(
        _closing_app=False,
        _live_chat_open=True,
        _live_chat_messages=["msg1"],
        live_chat_list=chat_list,
        live_chat_details_field=details,
    )
    with patch("ui.app_frame.speak_with_accessible_output", return_value=True):
        MainFrame._on_live_chat_incoming(frame, "msg2")
        assert frame._live_chat_messages == ["msg1", "msg2"]
        chat_list.Append.assert_called_once_with("msg2")
        chat_list.SetSelection.assert_called_once_with(1)
        details.ChangeValue.assert_called_once_with("msg2")


def test_on_live_chat_toggled_active_opens_box_and_speaks():
    chat_list = Mock()
    details = Mock()
    activities = Mock()
    frame = Mock(
        live_chat_list=chat_list,
        live_chat_details_field=details,
        activities=activities,
        _live_chat_open=False,
    )
    with patch("ui.app_frame.speak_with_accessible_output", return_value=True) as mock_speak:
        MainFrame._on_live_chat_toggled(frame, {
            "ok": True,
            "active": True,
            "messages": ["UserA: Olá", "UserB: Boa noite"]
        })
        assert frame._live_chat_open is True
        assert frame._live_chat_messages == ["UserA: Olá", "UserB: Boa noite"]
        chat_list.Set.assert_called_once_with(["UserA: Olá", "UserB: Boa noite"])
        activities.SetSelection.assert_called_once_with(3)
        chat_list.SetSelection.assert_called_once_with(1)
        details.ChangeValue.assert_called_once_with("UserB: Boa noite")
        chat_list.SetFocus.assert_called_once()
        frame.status.assert_called_once_with(
            "Chat da live aberto. Use as setas para rolar pelas mensagens; Esc ou Alt+Shift+T fecha o chat."
        )
        mock_speak.assert_called_once_with("UserB: Boa noite")


def test_on_live_chat_toggled_deactivated_calls_close():
    frame = Mock()
    MainFrame._on_live_chat_toggled(frame, {
        "ok": True,
        "active": False
    })
    frame._close_live_chat.assert_called_once_with(notify=True)


def test_on_live_chat_toggled_error():
    frame = Mock(_live_chat_open=True)
    MainFrame._on_live_chat_toggled(frame, {
        "ok": False,
        "error": "O chat da live ainda está carregando ou não está disponível."
    })
    assert frame._live_chat_open is False
    frame.status.assert_called_once_with(
        "O chat da live ainda está carregando ou não está disponível."
    )


def test_on_live_chat_read_success():
    frame = Mock()
    MainFrame._on_live_chat_read(frame, {
        "ok": True,
        "messages": ["User1: Top", "User2: Valeu"]
    })
    frame.status.assert_called_once_with(
        "Chat da live (2 mensagens): User1: Top | User2: Valeu"
    )


def test_on_live_chat_read_empty():
    frame = Mock()
    MainFrame._on_live_chat_read(frame, {
        "ok": True,
        "messages": []
    })
    frame.status.assert_called_once_with(
        "Nenhuma mensagem encontrada no chat da live no momento."
    )


def test_dispatch_live_chat_on_non_tiktok_rejects():
    frame = Mock(_active_name="Instagram")
    MainFrame.dispatch(frame, "toggle_live_chat")
    frame.status.assert_called_once_with(
        "O chat ao vivo está disponível apenas em transmissões do TikTok."
    )

    frame.reset_mock()
    MainFrame.dispatch(frame, "read_live_chat")
    frame.status.assert_called_once_with(
        "O chat ao vivo está disponível apenas em transmissões do TikTok."
    )


def test_dispatch_toggle_live_chat_opens_when_closed():
    frame = Mock(_active_name="TikTok", _live_chat_open=False)
    MainFrame.dispatch(frame, "toggle_live_chat")
    frame._open_live_chat.assert_called_once()


def test_dispatch_toggle_live_chat_closes_when_open():
    frame = Mock(_active_name="TikTok", _live_chat_open=True)
    MainFrame.dispatch(frame, "toggle_live_chat")
    frame._close_live_chat.assert_called_once_with(notify=True)


def test_open_live_chat_executes_with_force_start():
    mock_client = Mock(active=True)
    frame = Mock(_active_name="TikTok", clients={"TikTok": mock_client})
    MainFrame._open_live_chat(frame)
    mock_client.execute.assert_called_once()
    assert mock_client.execute.call_args[0][0] == "toggle_live_chat"
    assert mock_client.execute.call_args[0][1] == {"force_start": True}
    frame.status.assert_called_once_with("Abrindo chat da live...")


def test_close_live_chat_deactivates_and_restores_player():
    mock_client = Mock(active=True)
    activities = Mock()
    activities.GetSelection.return_value = 3
    details_field = Mock()
    frame = Mock(
        _active_name="TikTok",
        _live_chat_open=True,
        clients={"TikTok": mock_client},
        activities=activities,
        details_field=details_field,
    )
    MainFrame._close_live_chat(frame, notify=True)
    assert frame._live_chat_open is False
    mock_client.execute.assert_called_once_with("toggle_live_chat", {"force_stop": True}, pytest.approx(mock_client.execute.call_args[0][2]))
    activities.SetSelection.assert_called_once_with(0)
    details_field.SetFocus.assert_called_once()
    frame.status.assert_called_once_with("Chat da live fechado e leitura desativada.")


def test_live_chat_selected_updates_details_and_speaks_nvda():
    chat_list = Mock()
    chat_list.GetSelection.return_value = 1
    details = Mock()
    frame = Mock(
        live_chat_list=chat_list,
        live_chat_details_field=details,
        _live_chat_messages=["Msg 1", "Msg 2"],
    )
    with patch("ui.app_frame.speak_with_accessible_output", return_value=True) as mock_speak:
        MainFrame._live_chat_selected(frame)
        details.ChangeValue.assert_called_once_with("Msg 2")
        details.SetName.assert_called_once_with("Detalhes da mensagem 2 de 2, somente leitura")
        mock_speak.assert_called_once_with("Msg 2", interrupt=False)
