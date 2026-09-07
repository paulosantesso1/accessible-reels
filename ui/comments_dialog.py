from __future__ import annotations

from collections.abc import Callable, Iterable

import wx

from ui.shortcuts import set_shortcut


class CommentsDialog(wx.Dialog):
    """Janela nativa de comentários somente para leitura."""

    def __init__(
        self,
        parent: wx.Window,
        comments: Iterable[str],
        on_closed: Callable[[], None],
        *,
        platform: str = "TikTok",
    ) -> None:
        super().__init__(
            parent,
            title="Comentários do vídeo atual",
            size=(620, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._on_closed = on_closed
        self._closed_notified = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(panel, label="Comentários do vídeo atual")
        heading.SetName("Título: comentários do vídeo atual")
        sizer.Add(heading, 0, wx.ALL, 12)

        self.comments_field = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_MULTILINE | wx.TE_RICH2,
        )
        self.comments_field.SetName("Lista de comentários, somente leitura")
        sizer.Add(self.comments_field, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.close_button = wx.Button(panel, wx.ID_CANCEL, "&Fechar")
        self.close_button.SetName("Fechar comentários")
        set_shortcut(self.close_button, shortcut="Alt+F ou Esc")
        buttons.Add(self.close_button, 0, wx.ALIGN_RIGHT)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(sizer)

        self.close_button.Bind(wx.EVT_BUTTON, lambda _event: self.Close())
        self.Bind(wx.EVT_CLOSE, self._close)
        self.SetEscapeId(wx.ID_CANCEL)
        self.update_comments(comments)
        self.CentreOnParent()

    def update_comments(self, comments: Iterable[str]) -> None:
        values = tuple(comment.strip() for comment in comments if comment.strip())
        if values:
            text = "\r\n\r\n".join(
                f"Comentário {index}: {comment}"
                for index, comment in enumerate(values, start=1)
            )
            self.comments_field.SetName(
                f"Lista de comentários, somente leitura, {len(values)} comentários"
            )
        else:
            text = "Nenhum comentário encontrado."
            self.comments_field.SetName(
                "Lista de comentários, somente leitura, nenhum comentário"
            )
        self.comments_field.SetValue(text)
        self.comments_field.SetInsertionPoint(0)

    def focus_comments(self) -> None:
        self.Raise()
        self.comments_field.SetInsertionPoint(0)
        self.comments_field.SetFocus()

    def _close(self, event: wx.CloseEvent) -> None:
        if not self._closed_notified:
            self._closed_notified = True
            self._on_closed()
        event.Skip()
