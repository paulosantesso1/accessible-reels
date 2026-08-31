from __future__ import annotations

from collections.abc import Callable, Iterable

import wx


class CommentsDialog(wx.Dialog):
    """Janela nativa para leitura e publicação consciente de comentários."""

    def __init__(
        self,
        parent: wx.Window,
        comments: Iterable[str],
        on_post: Callable[[str], None],
        on_closed: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            title="Comentários do vídeo atual",
            size=(620, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._on_post = on_post
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
        self.write_button = wx.Button(panel, label="&Escrever comentário")
        self.write_button.SetName("Escrever comentário")
        self.close_button = wx.Button(panel, wx.ID_CANCEL, "&Fechar")
        self.close_button.SetName("Fechar comentários")
        buttons.Add(self.write_button, 1, wx.RIGHT, 8)
        buttons.Add(self.close_button, 1)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(sizer)

        self.write_button.Bind(wx.EVT_BUTTON, self._write_comment)
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

    def _write_comment(self, _event: wx.CommandEvent) -> None:
        dialog = wx.TextEntryDialog(
            self,
            "Digite o comentário. Selecione Publicar para enviá-lo ao TikTok.",
            "Escrever comentário",
            style=wx.OK | wx.CANCEL | wx.TE_MULTILINE,
        )
        publish_button = dialog.FindWindowById(wx.ID_OK)
        if publish_button is not None:
            publish_button.SetLabel("&Publicar")
            publish_button.SetName("Publicar comentário")
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            text = dialog.GetValue().strip()
        finally:
            dialog.Destroy()
        if not text:
            wx.MessageBox(
                "Digite um comentário antes de publicar.",
                "Comentário vazio",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.write_button.SetFocus()
            return
        self._on_post(text)

    def _close(self, event: wx.CloseEvent) -> None:
        if not self._closed_notified:
            self._closed_notified = True
            self._on_closed()
        event.Skip()
