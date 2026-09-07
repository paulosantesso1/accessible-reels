from unittest.mock import patch

from ui import app_frame


def test_copy_text_uses_wx_clipboard_on_non_windows():
    class Clipboard:
        def Open(self):
            return True

        def SetData(self, data):
            self.data = data
            return True

        def Close(self):
            pass

    clipboard = Clipboard()
    with patch.object(app_frame.sys, 'platform', 'linux'), \
            patch.object(app_frame.wx, 'TheClipboard', clipboard):
        assert app_frame._copy_text_to_clipboard('https://example.test/reel/1')
    assert clipboard.data.GetText() == 'https://example.test/reel/1'
