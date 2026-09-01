from __future__ import annotations

from collections.abc import Callable, Iterable

import wx

from tiktok.search import SearchResult


class SearchDialog(wx.Dialog):
    """Pesquisa e seleção acessível de vídeos do TikTok."""

    def __init__(
        self,
        parent: wx.Window,
        on_search: Callable[[str], None],
        on_open: Callable[[str], None],
        on_closed: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            title="Pesquisar vídeos",
            size=(700, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._on_search = on_search
        self._on_open = on_open
        self._on_closed = on_closed
        self._closed_notified = False
        self._results: tuple[SearchResult, ...] = ()

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(panel, label="Pesquisar vídeos no TikTok:")
        sizer.Add(label, 0, wx.ALL, 12)
        self.query_field = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.query_field.SetName("Termo da pesquisa")
        sizer.Add(self.query_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.search_button = wx.Button(panel, label="&Pesquisar")
        self.search_button.SetName("Pesquisar vídeos")
        sizer.Add(self.search_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        results_label = wx.StaticText(panel, label="Resultados:")
        sizer.Add(results_label, 0, wx.LEFT | wx.RIGHT, 12)
        self.results_list = wx.ListBox(panel)
        self.results_list.SetName("Resultados da pesquisa, nenhum resultado")
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.open_button = wx.Button(panel, label="&Abrir vídeo")
        self.open_button.SetName("Abrir vídeo selecionado")
        self.open_button.SetDefault()
        self.open_button.Enable(False)
        close_button = wx.Button(panel, wx.ID_CANCEL, "&Fechar")
        buttons.Add(self.open_button, 1, wx.RIGHT, 8)
        buttons.Add(close_button, 1)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(sizer)

        self.search_button.Bind(wx.EVT_BUTTON, self._search)
        self.query_field.Bind(wx.EVT_TEXT_ENTER, self._search)
        self.open_button.Bind(wx.EVT_BUTTON, self._open)
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self._open)
        self.results_list.Bind(wx.EVT_LISTBOX, self._selection_changed)
        close_button.Bind(wx.EVT_BUTTON, lambda _event: self.Close())
        self.Bind(wx.EVT_CLOSE, self._close)
        self.SetEscapeId(wx.ID_CANCEL)
        self.CentreOnParent()

    def focus_query(self) -> None:
        self.Raise()
        self.query_field.SetFocus()

    def update_results(self, results: Iterable[SearchResult]) -> None:
        self._results = tuple(results)
        self.results_list.Set([result.label for result in self._results])
        count = len(self._results)
        self.results_list.SetName(
            f"Resultados da pesquisa, {count} resultado{'s' if count != 1 else ''}"
        )
        self.open_button.Enable(count > 0)
        if count:
            self.results_list.SetSelection(0)
            self.results_list.SetFocus()
        else:
            self.query_field.SetFocus()

    def _search(self, _event: wx.CommandEvent) -> None:
        query = self.query_field.GetValue().strip()
        if not query:
            wx.MessageBox(
                "Digite algo para pesquisar.",
                "Pesquisa vazia",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.query_field.SetFocus()
            return
        self.search_button.Enable(False)
        self._on_search(query)

    def search_finished(self) -> None:
        self.search_button.Enable(True)

    def _selection_changed(self, _event: wx.CommandEvent) -> None:
        self.open_button.Enable(self.results_list.GetSelection() != wx.NOT_FOUND)

    def _open(self, _event: wx.CommandEvent) -> None:
        index = self.results_list.GetSelection()
        if index == wx.NOT_FOUND or not 0 <= index < len(self._results):
            return
        self._on_open(self._results[index].url)
        self.Close()

    def _close(self, event: wx.CloseEvent) -> None:
        if not self._closed_notified:
            self._closed_notified = True
            self._on_closed()
        event.Skip()
