"""Exercise native result-list Enter and menu commands without accessing accounts.

Run: python -m tests.search_navigation_smoke (Windows desktop required).
Network commands are simulated; controls, keyboard events and focus are real wx.
"""
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import wx

from ui.app_frame import MainFrame
from ui.webview_client import PLATFORM_URLS


def main():
    app = wx.App(False)
    errors = []
    platforms = iter(('TikTok', 'Instagram'))
    with patch('ui.app_frame.webview_profile_path', return_value=Path(tempfile.mkdtemp())), \
         patch('ui.app_frame.can_self_update', return_value=False), \
         patch.object(MainFrame, 'status'):
        frame = MainFrame()

        def check(fn):
            def run():
                try:
                    fn()
                except Exception as error:
                    errors.append(repr(error))
                    frame.Close()
            return run

        def menu(action):
            wx.PostEvent(frame, wx.CommandEvent(wx.wxEVT_MENU, frame._accelerator_ids[action]))

        def begin():
            name = next(platforms, None)
            if name is None:
                frame.Close()
                return
            frame._active_name = name
            frame.network.SetStringSelection(name)
            frame.platform_data[name] = {}
            frame.views[name] = Mock()
            frame.clients[name] = Mock(pending=None)
            urls = ([f'https://www.tiktok.com/@user/video/{i}' for i in (1, 2)] if name == 'TikTok'
                    else [f'https://www.instagram.com/reel/TEST{i}/' for i in (1, 2)])
            frame._result(name, 'collect_search_results', None,
                          {'ok': True, 'results': [{'url': url, 'author': name, 'description': str(i)}
                                                   for i, url in enumerate(urls)]})
            assert frame.results_list.GetCount() == 2
            frame.results_list.SetSelection(1)
            frame._result_selected(None)
            frame.query_field.SetFocus()
            down = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            down.SetKeyCode(wx.WXK_DOWN)
            down.SetEventObject(frame.query_field)
            wx.PostEvent(frame.query_field, down)
            wx.CallLater(100, check(enter_result))

        def enter_result():
            assert wx.Window.FindFocus() is frame.results_list
            enter = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            enter.SetKeyCode(wx.WXK_RETURN)
            enter.SetEventObject(frame.results_list)
            wx.PostEvent(frame.results_list, enter)
            wx.CallLater(150, check(opened))

        def opened():
            client = frame.clients[frame._active_name]
            assert client.navigate.call_args.args[0] == frame._results[1].url
            assert frame.activities.GetSelection() == 0
            assert frame.player_focus_target.IsShownOnScreen()
            assert wx.Window.FindFocus() is frame.player_focus_target
            client.navigate.call_args.args[1]()
            assert client.execute.call_args.args[0] == 'play'
            client.execute.call_args.args[2]({'ok': True, 'paused': False})
            menu('return_results')
            wx.CallLater(150, check(returned))

        def returned():
            assert frame.activities.GetSelection() == 2
            assert frame.results_list.GetSelection() == 1
            assert wx.Window.FindFocus() is frame.results_list
            menu('home')
            wx.CallLater(150, check(feed))

        def feed():
            assert frame.activities.GetSelection() == 0
            frame.clients[frame._active_name].navigate.assert_called_with(PLATFORM_URLS[frame._active_name])
            print(frame._active_name + ': list -> Enter -> player -> results -> feed PASS', flush=True)
            wx.CallAfter(check(begin))

        frame.Show()
        wx.CallAfter(check(begin))
        timer = wx.CallLater(15000, lambda: (errors.append('timeout'), frame.Close()))
        app.MainLoop()
        timer.Stop()
    print('Errors:', errors, flush=True)
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
