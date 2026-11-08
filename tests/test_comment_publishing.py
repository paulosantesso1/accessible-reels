import json
from unittest.mock import Mock, patch

import pytest
import wx

from ui.app_frame import COMMENT_LIMITS, MainFrame, prepare_comment
from ui.webview_client import MAX_COMMENT_LENGTH, WebViewClient


def make_client(platform='TikTok'):
    view = Mock()
    view.GetCurrentURL.return_value = {
        'TikTok': 'https://www.tiktok.com/',
        'Instagram': 'https://www.instagram.com/reels/',
        'YouTube': 'https://www.youtube.com/shorts/',
    }[platform]
    return WebViewClient(view, platform, Mock(), Mock())


def start_post(client, text='Comentário aprovado'):
    with patch('ui.webview_client.wx.CallLater'), patch('ui.webview_client.webview_native.evaluate'):
        client.execute('post_comment', {'text': text}, Mock())
    return client.pending['token']


def text_message(token, text, identifier=1):
    event = Mock()
    event.GetURL.return_value = 'https://www.tiktok.com/'
    event.GetString.return_value = json.dumps({'type': 'text', 'token': token, 'id': identifier, 'text': text})
    return event


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram', 'YouTube'])
def test_post_comment_is_sent_to_the_page_with_its_text(platform):
    client = make_client(platform)
    with patch('ui.webview_client.wx.CallLater'), patch('ui.webview_client.webview_native.evaluate') as evaluate:
        client.execute('post_comment', {'text': 'Olá'}, Mock())
    assert client.pending['approved_text'] == 'Olá'
    assert '"post_comment", {"text": "Ol\\u00e1"}' in evaluate.call_args.args[1]


def test_page_can_type_only_the_approved_text_once():
    client = make_client()
    token = start_post(client)
    with patch('ui.webview_client.webview_native.insert_text') as insert:
        client._message(text_message(token, 'Comentário aprovado'))
        client._message(text_message(token, 'Comentário aprovado', identifier=2))
    insert.assert_called_once()
    assert insert.call_args.args[1] == 'Comentário aprovado'


def test_page_cannot_type_a_different_text():
    client = make_client()
    token = start_post(client)
    with patch('ui.webview_client.webview_native.insert_text') as insert:
        client._message(text_message(token, 'Texto trocado pelo site', identifier=3))
    insert.assert_not_called()
    # The page learns at once why nothing was typed.
    script = client.view.RunScriptAsync.call_args.args[0]
    assert script.startswith('window.__accessibleClickDone?.(3, ')
    assert '"ok": false' in script and 'diferente do confirmado' in json.loads(script.split(', ', 1)[1][:-2])['error']


def test_typing_is_refused_outside_a_comment_command():
    client = make_client()
    with patch('ui.webview_client.wx.CallLater'), patch('ui.webview_client.webview_native.evaluate'):
        client.execute('toggle_like', 'Comentário aprovado', Mock())
    with patch('ui.webview_client.webview_native.insert_text') as insert:
        client._message(text_message(client.pending['token'], 'Comentário aprovado'))
    insert.assert_not_called()


def test_typing_is_refused_with_another_commands_token():
    client = make_client()
    start_post(client)
    with patch('ui.webview_client.webview_native.insert_text') as insert:
        client._message(text_message('outro-token', 'Comentário aprovado'))
    insert.assert_not_called()


def test_typing_refuses_text_longer_than_any_network_accepts():
    client = make_client()
    text = 'a' * (MAX_COMMENT_LENGTH + 1)
    token = start_post(client, text)
    with patch('ui.webview_client.webview_native.insert_text') as insert:
        client._message(text_message(token, text))
    insert.assert_not_called()


def test_typing_result_is_returned_to_the_waiting_page():
    client = make_client()
    token = start_post(client)
    with patch('ui.webview_client.webview_native.insert_text',
               side_effect=lambda view, text, callback, valid: callback(True, None)):
        client._message(text_message(token, 'Comentário aprovado', identifier=7))
    script = client.view.RunScriptAsync.call_args.args[0]
    assert script.startswith('window.__accessibleClickDone?.(7, ')
    assert '"ok": true' in script


def test_insert_text_uses_trusted_devtools_input():
    from ui import webview_native
    callback = Mock()
    with patch.object(webview_native, 'call_devtools') as devtools:
        webview_native.insert_text('view', 'Olá', callback)
        method, parameters, done = devtools.call_args.args[1:]
        done({}, None)
    assert (method, parameters) == ('Input.insertText', {'text': 'Olá'})
    callback.assert_called_once_with(True, None)


def test_insert_text_is_skipped_when_the_page_changed():
    from ui import webview_native
    with patch.object(webview_native, 'call_devtools') as devtools, \
         patch.object(webview_native.wx, 'CallAfter') as deferred:
        webview_native.insert_text('view', 'Olá', Mock(), still_valid=lambda: False)
    devtools.assert_not_called()
    assert deferred.call_args.args[1] is False


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram', 'YouTube'])
def test_prepare_comment_keeps_a_single_line(platform):
    assert prepare_comment('  Muito\n bom   vídeo ', platform) == 'Muito bom vídeo'


def test_prepare_comment_refuses_empty_text():
    with pytest.raises(ValueError, match='Digite um comentário'):
        prepare_comment(' \n ', 'TikTok')


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram', 'YouTube'])
def test_prepare_comment_respects_each_network_limit(platform):
    limit = COMMENT_LIMITS[platform]
    assert prepare_comment('a' * limit, platform) == 'a' * limit
    with pytest.raises(ValueError, match=f'aceita até {limit} caracteres'):
        prepare_comment('a' * (limit + 1), platform)


def publish_frame(text='Comentário novo', platform='TikTok', pending=None):
    frame = Mock()
    frame._reply_target = None
    frame._active_name = platform
    frame.comment_entry.GetValue.return_value = text
    frame.clients = {platform: Mock(pending=pending)}
    return frame


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram', 'YouTube'])
def test_publish_sends_the_comment_after_confirmation(platform):
    frame = publish_frame(platform=platform)
    with patch('ui.app_frame.wx.MessageBox', return_value=wx.YES) as confirm:
        MainFrame._publish_comment(frame)
    assert platform in confirm.call_args.args[0]
    assert confirm.call_args.args[2] & wx.NO_DEFAULT
    frame.publish_button.Disable.assert_called_once()
    frame.dispatch.assert_called_once_with('post_comment', {'text': 'Comentário novo'})


def test_publish_does_nothing_when_the_confirmation_is_refused():
    frame = publish_frame()
    with patch('ui.app_frame.wx.MessageBox', return_value=wx.NO):
        MainFrame._publish_comment(frame)
    frame.dispatch.assert_not_called()
    frame.publish_button.Disable.assert_not_called()
    frame.comment_entry.SetFocus.assert_called()


def test_publish_does_not_ask_while_another_command_runs():
    frame = publish_frame(pending={'token': 'x'})
    with patch('ui.app_frame.wx.MessageBox') as confirm:
        MainFrame._publish_comment(frame)
    confirm.assert_not_called()
    frame.dispatch.assert_not_called()


def test_publish_explains_an_empty_comment_without_asking():
    frame = publish_frame(text='   ')
    with patch('ui.app_frame.wx.MessageBox') as confirm:
        MainFrame._publish_comment(frame)
    confirm.assert_not_called()
    frame.status.assert_called_once_with('Digite um comentário antes de publicar.')


def result_frame(platform='TikTok'):
    frame = Mock()
    frame._active_name = platform
    frame.platform_data = {platform: {}}
    return frame


def test_published_comment_clears_the_text_and_reloads_the_list():
    frame = result_frame()
    with patch('ui.app_frame.wx.CallAfter') as deferred:
        MainFrame._result(frame, 'TikTok', 'post_comment', {'text': 'Oi'}, {'ok': True})
    frame.publish_button.Enable.assert_called_once()
    frame.comment_entry.Clear.assert_called_once()
    deferred.assert_called_once_with(frame.dispatch, 'open_comments')
    assert frame.platform_data['TikTok']['comment_posted'] == 'Comentário publicado.'


def test_failed_comment_keeps_the_text_and_enables_publish_again():
    frame = result_frame()
    MainFrame._result(frame, 'TikTok', 'post_comment', {'text': 'Oi'},
                      {'ok': False, 'error': 'O vídeo mudou. O comentário não foi enviado.'})
    frame.publish_button.Enable.assert_called_once()
    frame.comment_entry.Clear.assert_not_called()
    frame._platform_error.assert_called_once_with('TikTok', 'O vídeo mudou. O comentário não foi enviado.')


def test_reloaded_list_announces_the_published_comment():
    frame = result_frame()
    frame.platform_data['TikTok'] = {'comment_posted': 'Comentário publicado.'}
    MainFrame._result(frame, 'TikTok', 'open_comments', None,
                      {'ok': True, 'comments': [{'id': '1', 'text': 'a'}, {'id': '2', 'text': 'b'}]})
    frame.status.assert_called_with('Comentário publicado. 2 comentários carregados.')
    assert 'comment_posted' not in frame.platform_data['TikTok']


def reply_frame(selection=1, items=({'id': 'c1', 'text': 'ana: Primeiro'}, {'id': 'c2', 'text': 'bia: Segundo'})):
    frame = Mock()
    frame._reply_target = None
    frame._comment_items = items
    frame.comments_list.GetSelection.return_value = selection
    frame._selected_comment.side_effect = lambda: MainFrame._selected_comment(frame)
    frame._set_reply_target.side_effect = lambda target: MainFrame._set_reply_target(frame, target)
    frame._reply_to_selected.side_effect = lambda: MainFrame._reply_to_selected(frame)
    return frame


def test_reply_button_targets_the_selected_comment():
    frame = reply_frame()
    MainFrame._toggle_reply(frame)
    assert frame._reply_target == {'id': 'c2', 'text': 'bia: Segundo', 'index': 2}
    frame.reply_button.SetLabel.assert_called_with('Cancelar resposta')
    assert 'resposta ao comentário 2: bia: Segundo' in frame.comment_entry.SetName.call_args.args[0]
    frame.status.assert_called_once_with(
        'Respondendo ao comentário 2: bia: Segundo. Escreva a resposta e pressione Enter para publicar.')
    frame.comment_entry.SetFocus.assert_called_once()


def test_reply_button_cancels_an_active_reply():
    frame = reply_frame()
    MainFrame._toggle_reply(frame)
    MainFrame._toggle_reply(frame)
    assert frame._reply_target is None
    frame.reply_button.SetLabel.assert_called_with('Responder ao comentário selecionado')
    frame.status.assert_called_with('Resposta cancelada. O campo volta a publicar um comentário novo.')


def test_reply_button_asks_to_choose_a_comment_first():
    frame = reply_frame(selection=wx.NOT_FOUND)
    MainFrame._toggle_reply(frame)
    assert frame._reply_target is None
    frame.status.assert_called_once_with('Escolha um comentário na lista antes de responder.')
    frame.comments_list.SetFocus.assert_called_once()


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram', 'YouTube'])
def test_reply_is_sent_with_the_replied_comment_after_confirmation(platform):
    frame = publish_frame(text='Concordo', platform=platform)
    frame._reply_target = {'id': 'c2', 'text': 'bia: Segundo', 'index': 2}
    with patch('ui.app_frame.wx.MessageBox', return_value=wx.YES) as confirm:
        MainFrame._publish_comment(frame)
    question = confirm.call_args.args[0]
    assert question.startswith(f'Responder ao comentário 2 no {platform}?')
    assert 'Comentário: bia: Segundo' in question and 'Resposta: Concordo' in question
    frame.status.assert_called_with('Publicando resposta...')
    frame.dispatch.assert_called_once_with(
        'post_comment', {'text': 'Concordo', 'replyTo': 'c2', 'replyText': 'bia: Segundo'})


def test_published_reply_is_announced_and_the_field_returns_to_new_comments():
    frame = result_frame()
    with patch('ui.app_frame.wx.CallAfter'):
        MainFrame._result(frame, 'TikTok', 'post_comment', {'text': 'Oi', 'replyTo': 'c2', 'replyText': 'bia'},
                          {'ok': True})
    frame._set_reply_target.assert_called_once_with(None)
    assert frame.platform_data['TikTok']['comment_posted'] == 'Resposta publicada.'
    frame.status.assert_called_with('Resposta publicada. Atualizando a lista de comentários.')


def test_failed_reply_keeps_the_reply_target():
    frame = result_frame()
    MainFrame._result(frame, 'TikTok', 'post_comment', {'text': 'Oi', 'replyTo': 'c2'},
                      {'ok': False, 'error': 'O comentário selecionado não está mais disponível.'})
    frame._set_reply_target.assert_not_called()
    frame.comment_entry.Clear.assert_not_called()


def test_reply_target_is_dropped_when_its_comment_is_no_longer_listed():
    frame = reply_frame()
    frame._active_name = 'TikTok'
    frame._reply_target = {'id': 'c1', 'text': 'ana: Primeiro', 'index': 1}
    # Another video: same id, different comment.
    frame.platform_data = {'TikTok': {'comments': [{'id': 'c1', 'text': 'carla: Outro vídeo'}]}}
    MainFrame._render_comments(frame)
    assert frame._reply_target is None


def test_reply_target_survives_a_refresh_of_the_same_comments():
    frame = reply_frame()
    frame._active_name = 'TikTok'
    target = {'id': 'c1', 'text': 'ana: Primeiro', 'index': 1}
    frame._reply_target = target
    frame.platform_data = {'TikTok': {'comments': [{'id': 'c1', 'text': 'ana: Primeiro'}]}}
    MainFrame._render_comments(frame)
    assert frame._reply_target is target


def test_ctrl_r_on_a_comment_answers_that_comment():
    frame = reply_frame()
    frame.activities.GetSelection.return_value = 1
    with patch('ui.app_frame.wx.Window.FindFocus', return_value=frame.comments_list):
        MainFrame.return_to_results(frame)
    assert frame._reply_target == {'id': 'c2', 'text': 'bia: Segundo', 'index': 2}
    frame.comment_entry.SetFocus.assert_called_once()
    # Did not go back to the results.
    frame.activities.SetSelection.assert_not_called()
    frame.query_field.SetFocus.assert_not_called()


def test_ctrl_r_elsewhere_still_returns_to_the_results():
    frame = reply_frame()
    frame.activities.GetSelection.return_value = 1
    frame.platform_data = {'TikTok': {}}
    frame._active_name = 'TikTok'
    with patch('ui.app_frame.wx.Window.FindFocus', return_value=frame.comment_entry):
        MainFrame.return_to_results(frame)
    assert frame._reply_target is None
    frame.status.assert_called_once_with('Faça uma pesquisa para carregar a lista de resultados.')


def write_frame(page=0, pending=None):
    frame = reply_frame()
    frame._active_name = 'TikTok'
    frame.activities.GetSelection.return_value = page
    frame.clients = {'TikTok': Mock(pending=pending)}
    frame.platform_data = {'TikTok': {}}
    return frame


def test_alt_v_from_the_player_opens_the_comments_in_the_text_field():
    frame = write_frame(page=0)
    MainFrame.write_comment(frame)
    assert frame.platform_data['TikTok']['focus_comment_entry'] is True
    frame.dispatch.assert_called_once_with('open_comments')


def test_alt_v_on_the_comments_screen_goes_to_the_field_for_a_new_comment():
    frame = write_frame(page=1)
    frame._reply_target = {'id': 'c1', 'text': 'ana: Primeiro', 'index': 1}
    MainFrame.write_comment(frame)
    assert frame._reply_target is None
    frame.comment_entry.SetFocus.assert_called_once()
    frame.dispatch.assert_not_called()
    frame.status.assert_called_once_with('Escreva o comentário para o vídeo atual e pressione Enter para publicar.')


def test_alt_v_waits_for_a_running_command():
    frame = write_frame(page=0, pending={'token': 'x'})
    MainFrame.write_comment(frame)
    frame.dispatch.assert_not_called()
    assert 'focus_comment_entry' not in frame.platform_data['TikTok']


def test_comments_opened_by_alt_v_land_in_the_text_field():
    frame = result_frame()
    frame.platform_data['TikTok'] = {'focus_comment_entry': True}
    MainFrame._result(frame, 'TikTok', 'open_comments', None, {'ok': True, 'comments': [{'id': '1', 'text': 'a'}]})
    frame.comment_entry.SetFocus.assert_called_once()
    frame.comments_list.SetFocus.assert_not_called()
    frame.status.assert_called_with('1 comentários carregados. Escreva o comentário e pressione Enter para publicar.')
    assert 'focus_comment_entry' not in frame.platform_data['TikTok']


def test_comments_opened_normally_still_start_on_the_list():
    frame = result_frame()
    MainFrame._result(frame, 'TikTok', 'open_comments', None, {'ok': True, 'comments': []})
    frame.comments_list.SetFocus.assert_called_once()
    frame.comment_entry.SetFocus.assert_not_called()


def test_failed_alt_v_does_not_leave_the_field_focus_for_later():
    frame = result_frame()
    frame.platform_data['TikTok'] = {'focus_comment_entry': True}
    MainFrame._result(frame, 'TikTok', 'open_comments', None, {'ok': False, 'error': 'Sem comentários.'})
    assert 'focus_comment_entry' not in frame.platform_data['TikTok']


def test_alt_v_and_ctrl_r_are_listed_with_their_meaning():
    from ui.shortcuts import DEFAULT_SHORTCUTS, SHORTCUT_DEFINITIONS
    labels = {item.action: item.label for item in SHORTCUT_DEFINITIONS}
    assert DEFAULT_SHORTCUTS['write_comment'] == 'Alt+V'
    assert labels['write_comment'] == 'Escrever comentário no vídeo atual'
    assert DEFAULT_SHORTCUTS['return_results'] == 'Ctrl+R'
    assert 'responder ao comentário selecionado' in labels['return_results']
    assert len(set(DEFAULT_SHORTCUTS.values())) == len(DEFAULT_SHORTCUTS)
