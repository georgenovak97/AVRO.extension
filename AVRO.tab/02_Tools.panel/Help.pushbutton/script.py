# -*- coding: utf-8 -*-
"""AVRO Help: browse and read a local Obsidian Markdown vault."""
import os
import sys
import time
import System

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Windows.Forms")

from System.Windows import (
    Thickness, VerticalAlignment, Visibility, TextWrapping, FontWeights,
    GridLength, GridUnitType, WindowState,
)
from System.Windows.Controls import TreeViewItem, TextBlock, StackPanel, Orientation, ListBoxItem
from System.Windows.Media import Color, Geometry, SolidColorBrush, Stretch
from System.Windows.Media.Imaging import BitmapImage
from System.Windows.Documents import Bold, Run
from System.Windows.Input import Key
from System.Windows.Shapes import Path as WpfPath
from System.Windows.Forms import FolderBrowserDialog, DialogResult
from System.Diagnostics import Process

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_EXT_LIB = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "..", "lib"))
if _EXT_LIB not in sys.path:
    sys.path.insert(0, _EXT_LIB)

import config
import help_renderer
import help_scanner
import help_toc
import i18n
import ui_notify
import ui_theme
import ui_utils


class HelpDialog(object):
    _active_instance = None

    def __init__(self):
        self.win = None
        self.ui = None
        self.root = None
        self.current_path = None
        self._current_text = ""
        self._headings = []
        self.search_mode = False
        self.doc_count = 0
        self._history = []
        self._history_index = -1
        self._history_navigating = False
        self._selecting_tree_file = False
        self._selecting_search = False
        self._last_escape_press_at = 0.0

    def _palette(self):
        return ui_theme.DARK if config.load().get("ui_theme") == "dark" else ui_theme.LIGHT

    def _apply_text(self):
        self.win.Title = i18n.t("help_app_title")
        self.ui.TocTitle.Text = i18n.t("help_toc_title")
        self.ui.StatusText.Text = ""
        self.ui.BtnDocuments.Content = i18n.t("help_btn_documents")
        self.ui.BtnDocuments.ToolTip = i18n.t("help_btn_documents_tooltip")
        self.ui.BtnRefresh.Content = i18n.t("help_btn_refresh")
        self.ui.BtnRefresh.ToolTip = i18n.t("help_btn_refresh_tooltip")
        self.ui.BtnHome.ToolTip = i18n.t("help_home_tooltip")
        self.ui.SearchHint.Text = i18n.t("help_search_placeholder")
        self.ui.SearchBox.ToolTip = i18n.t("help_search_placeholder")

    def _header(self, text, geometry):
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        icon = WpfPath()
        icon.Data = Geometry.Parse(geometry)
        icon.Width = 16
        icon.Height = 16
        icon.Stretch = Stretch.Uniform
        icon.Margin = Thickness(3, 1, 5, 1)
        palette = self._palette()
        color = palette["TreeIcon"].lstrip("#")
        icon.Stroke = SolidColorBrush(Color.FromRgb(
            int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)))
        icon.StrokeThickness = 1.2
        panel.Children.Add(icon)
        label = TextBlock(Text=text)
        label.VerticalAlignment = VerticalAlignment.Center
        panel.Children.Add(label)
        return panel

    def _theme_changed(self):
        if self.win is not None:
            palette = self._palette()
            ui_theme.apply_window_theme(self.win, palette)
            if self.current_path and os.path.isfile(self.current_path):
                self._show_file(self.current_path)

    def _add_file(self, parent, path):
        item = TreeViewItem()
        item.Header = self._header(
            os.path.splitext(os.path.basename(path))[0],
            "M3,1 L12,1 L16,5 L16,17 L3,17 Z M12,1 L12,5 L16,5 M5,9 L14,9 M5,12 L14,12 M5,15 L11,15")
        item.Tag = path
        item.Uid = "file"
        item.Selected += self._file_selected
        parent.Items.Add(item)

    def _add_search_item(self):
        item = TreeViewItem()
        item.Header = self._header(
            i18n.t("help_home"),
            "M2,9 L9,2 L16,9 M4,9 L4,16 L14,16 L14,9 M8,16 L8,12 L10,12 L10,16")
        item.Tag = "__search__"
        item.Selected += self._search_selected
        item.PreviewMouseLeftButtonDown += self._search_mouse_down
        self.ui.DocumentTree.Items.Add(item)

    def _search_mouse_down(self, sender, args):
        if sender.IsSelected:
            self._search_selected(sender, args)

    def _add_folder(self, parent, node, is_root=False):
        item = TreeViewItem()
        item.Header = self._header(
            node.name, "M1,4 L6,4 L8,6 L17,6 L17,16 L1,16 Z")
        item.Tag = node.path
        item.IsExpanded = is_root
        for folder in node.folders:
            self._add_folder(item, folder, is_root=False)
        for path in node.files:
            self._add_file(item, path)
        parent.Items.Add(item)

    def _load_tree(self):
        self.ui.DocumentTree.Items.Clear()
        self._add_search_item()
        path = config.load().get("docs_path") or ""
        if not os.path.isdir(path):
            return
        self.root, count = help_scanner.scan_documents(path)
        self.doc_count = count
        self._add_folder(self.ui.DocumentTree, self.root, is_root=True)

    def _file_selected(self, sender, args):
        path = getattr(sender, "Tag", None)
        if (not self._selecting_tree_file and path and
                os.path.isfile(path)):
            self._show_file(path)

    def _select_file_in_tree(self, target_path):
        """Expand the document path and highlight the opened file."""
        target_path = os.path.normcase(os.path.abspath(target_path))

        def find_in(items):
            for item in items:
                tag = getattr(item, "Tag", None)
                if tag is None or tag == "__search__":
                    continue
                if getattr(item, "Uid", None) == "file":
                    if os.path.normcase(os.path.abspath(tag)) == target_path:
                        self._selecting_tree_file = True
                        try:
                            item.IsSelected = True
                            item.BringIntoView()
                        finally:
                            self._selecting_tree_file = False
                        return True
                    continue
                folder_path = os.path.normcase(os.path.abspath(tag))
                if target_path.startswith(folder_path + os.sep):
                    item.IsExpanded = True
                    if find_in(item.Items):
                        return True
            return False

        find_in(self.ui.DocumentTree.Items)

    def _search_selected(self, sender, args):
        if self._selecting_search:
            return
        self.search_mode = True
        self.ui.SearchBar.Visibility = Visibility.Visible
        self.ui.PathText.Text = u"{} {}".format(
            self.doc_count, i18n.t("help_documents_label"))
        self.ui.StatusText.Text = ""
        self._headings = []
        self._fill_help_guide()
        self._update_bookmark_button()
        self.ui.SearchBox.Text = ""
        self.ui.SearchBox.Focus()
        self._run_search("")

    def _go_home(self, sender=None, args=None):
        if not self._history or self._history[-1] != "__search__":
            self._history = self._history[:self._history_index + 1]
            self._history.append("__search__")
            self._history_index = len(self._history) - 1
        self._selecting_search = True
        try:
            for item in self.ui.DocumentTree.Items:
                if getattr(item, "Tag", None) == "__search__":
                    item.IsSelected = True
                    item.BringIntoView()
                    break
        finally:
            self._selecting_search = False
        self._search_selected(None, None)
        self._update_navigation_buttons()

    def _update_bookmark_button(self):
        if self.ui is None:
            return
        if not self.current_path or self.search_mode:
            self.ui.BtnBookmark.IsEnabled = False
            self.ui.BookmarkIcon.Fill = None
            return
        self.ui.BtnBookmark.IsEnabled = True
        bookmarked = config.is_bookmarked(self.current_path)
        if bookmarked:
            color = self._palette()["TreeConnector"].lstrip("#")
            self.ui.BookmarkIcon.Fill = SolidColorBrush(Color.FromRgb(
                int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)))
            self.ui.BtnBookmark.ToolTip = i18n.t("help_bookmark_remove")
        else:
            self.ui.BookmarkIcon.Fill = None
            self.ui.BtnBookmark.ToolTip = i18n.t("help_bookmark_add")

    def _toggle_bookmark(self, sender=None, args=None):
        if not self.current_path or self.search_mode:
            return
        if config.is_bookmarked(self.current_path):
            config.remove_bookmark(self.current_path)
        else:
            config.add_bookmark(self.current_path)
        self._update_bookmark_button()

    def _update_navigation_buttons(self):
        if self.ui is None:
            return
        self.ui.BtnBack.IsEnabled = self._history_index > 0
        self.ui.BtnForward.IsEnabled = (
            self._history_index >= 0
            and self._history_index < len(self._history) - 1)

    def _go_back(self, sender=None, args=None):
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._history_navigating = True
        try:
            target = self._history[self._history_index]
            if target == "__search__":
                self._search_selected(None, None)
            else:
                self._show_file(target)
        finally:
            self._history_navigating = False
            self._update_navigation_buttons()

    def _go_forward(self, sender=None, args=None):
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._history_navigating = True
        try:
            target = self._history[self._history_index]
            if target == "__search__":
                self._search_selected(None, None)
            else:
                self._show_file(target)
        finally:
            self._history_navigating = False
            self._update_navigation_buttons()

    def _run_search(self, query):
        path = config.load().get("docs_path") or ""
        query = (query or "").strip()
        if not query:
            bookmarks = [item for item in config.documents_under_path(
                config.load_bookmarks(), path) if os.path.isfile(item)]
            recent = [item for item in config.documents_under_path(
                config.load_recent_documents(), path) if os.path.isfile(item)]
            self._navigate_html(help_renderer.home_page_html(
                bookmarks, recent, self._palette(),
                i18n.t("help_bookmarks_section"),
                i18n.t("help_recent_section"),
                i18n.t("help_bookmarks_empty"),
                i18n.t("help_recent_empty")))
            return
        results = help_scanner.search_documents(path, query)
        if os.path.isfile(query) and query.lower().endswith(".md"):
            try:
                text = help_scanner.read_text(query)
                result = (query, " ".join(text[:220].split()))
                if not any(item[0].lower() == query.lower()
                           for item in results):
                    results.insert(0, result)
            except Exception:
                pass
        self._navigate_html(help_renderer.search_results_html(
            results, query, self._palette(), i18n.t("help_search"),
            i18n.t("help_search_no_results"), i18n.t("help_search_results")))

    def _clear_search(self):
        self.ui.SearchBox.Text = ""
        self.ui.SearchBox.Focus()

    def _on_browser_navigating(self, sender, args):
        uri = args.Uri
        if (uri is not None and uri.Scheme == "help" and
                uri.Host == "toc-clearselection"):
            self.ui.TocTree.SelectedItem = None
            args.Cancel = True
            return
        if uri is None or uri.Scheme != "help" or uri.Host != "open":
            if uri is not None and uri.Scheme in ("http", "https"):
                args.Cancel = True
                Process.Start(uri.AbsoluteUri)
            return
        query = uri.Query
        if query.startswith("?path="):
            path = System.Uri.UnescapeDataString(query[6:]).replace("/", os.sep)
            if os.path.isfile(path):
                self._show_file(path)
        args.Cancel = True

    def _show_file(self, path):
        try:
            text = help_scanner.read_text(path)
            if not self._history_navigating:
                self._history = self._history[:self._history_index + 1]
                if self.search_mode and (
                        not self._history or self._history[-1] != "__search__"):
                    self._history.append("__search__")
                if not self._history or self._history[-1].lower() != path.lower():
                    self._history.append(path)
                self._history_index = len(self._history) - 1
            self.current_path = path
            self._current_text = text
            self.search_mode = False
            self.ui.SearchBar.Visibility = Visibility.Collapsed
            config.add_recent_document(path)
            self.ui.PathText.Text = os.path.splitext(os.path.basename(path))[0]
            self.ui.StatusText.Text = path
            self._navigate_html(help_renderer.themed_html(
                text, self._palette(), os.path.basename(path),
                os.path.dirname(path), "",
                config.load().get("docs_path") or ""))
            self._headings = help_toc.extract_headings(text)
            self.ui.TocTitle.Text = i18n.t("help_toc_title")
            self._fill_toc()
            self._select_file_in_tree(path)
            self._update_navigation_buttons()
            self._update_bookmark_button()
        except Exception as ex:
            self.ui.PathText.Text = u"{}: {}".format(i18n.t("help_select_file"), ex)

    def _fill_toc(self):
        self.ui.TocTree.Items.Clear()
        if not self._headings:
            empty = TextBlock(Text=i18n.t("help_toc_empty"))
            empty.SetResourceReference(TextBlock.ForegroundProperty, "TextMain")
            self.ui.TocTree.Items.Add(empty)
            return
        for level, title in self._headings:
            text = TextBlock(Text=title)
            text.Margin = Thickness((level - 1) * 12, 0, 0, 0)
            item = ListBoxItem(Content=text, Tag=title)
            item.Selected += self._toc_selected
            self.ui.TocTree.Items.Add(item)

    def _fill_help_guide(self):
        self.ui.TocTitle.Text = i18n.t("help_guide_title")
        self.ui.TocTree.Items.Clear()
        guide = TextBlock()
        guide.TextWrapping = TextWrapping.Wrap
        guide.SetResourceReference(TextBlock.ForegroundProperty, "TextMuted")
        guide.Margin = Thickness(9, 8, 9, 8)
        guide.FontWeight = FontWeights.Normal
        for title, body in i18n.t("help_guide_sections"):
            guide.Inlines.Add(Bold(Run(title)))
            guide.Inlines.Add(Run(u"\n{}\n\n".format(body)))
        item = ListBoxItem(Content=guide)
        item.IsEnabled = False
        item.Focusable = False
        self.ui.TocTree.Items.Add(item)

    def _toc_selected(self, sender, args):
        title = getattr(sender, "Tag", None)
        if title and self.current_path:
            self._navigate_html(help_renderer.themed_html(
                self._current_text, self._palette(),
                os.path.basename(self.current_path),
                os.path.dirname(self.current_path),
                help_renderer._slug(title),
                config.load().get("docs_path") or ""))

    def _navigate_html(self, html):
        if self.win is None:
            return

        def navigate():
            if self.win is not None and self.ui is not None:
                self.ui.MarkdownBrowser.NavigateToString(html)

        self.win.Dispatcher.BeginInvoke(System.Action(navigate))

    def _choose_documents(self, sender, args):
        dialog = FolderBrowserDialog()
        dialog.Description = i18n.t("help_btn_documents_tooltip")
        current = config.load().get("docs_path") or ""
        if os.path.isdir(current):
            dialog.SelectedPath = current
        if dialog.ShowDialog() == DialogResult.OK:
            config.set_value("docs_path", dialog.SelectedPath)
            config.prune_bookmarks(dialog.SelectedPath)
            config.prune_recent_documents(dialog.SelectedPath)
            self.current_path = None
            self._current_text = ""
            self._load_tree()
            self._go_home()

    def _refresh_documents(self, sender, args):
        docs_path = config.load().get("docs_path") or ""
        config.prune_bookmarks(docs_path)
        config.prune_recent_documents(docs_path)
        self._load_tree()
        if self.current_path and os.path.isfile(self.current_path):
            self._show_file(self.current_path)

    def _on_window_keydown(self, sender, args):
        if args.Key != Key.Escape:
            self._last_escape_press_at = 0.0
            return
        now = time.time()
        if now - self._last_escape_press_at <= 0.6:
            self._last_escape_press_at = 0.0
            args.Handled = True
            self.win.Close()
            return
        self._last_escape_press_at = now

    def _init_window(self):
        self.win = ui_utils.load_xaml(_THIS_DIR)
        icon_path = os.path.join(_THIS_DIR, "icon.png")
        if os.path.isfile(icon_path):
            self.win.Icon = BitmapImage(System.Uri(icon_path))
        self.win.PreviewKeyDown += self._on_window_keydown
        self.ui = ui_utils.NamedUiControls(
            self.win, ("DocumentTree", "MarkdownBrowser", "PathText", "BtnBack",
                       "BtnForward", "BtnHome", "BtnBookmark", "BookmarkIcon",
                       "SearchBar", "SearchBox", "SearchHint",
                       "BtnClearSearch", "TocTitle", "TocTree", "BtnDocuments",
                       "BtnRefresh", "StatusText"))
        self._restore_panel_widths()
        ui_theme.apply_window_theme(self.win, self._palette())
        self._apply_text()
        self.win.Closing += self._on_window_closing
        self.ui.BtnDocuments.Click += self._choose_documents
        self.ui.BtnRefresh.Click += self._refresh_documents
        self.ui.BtnBack.Click += self._go_back
        self.ui.BtnForward.Click += self._go_forward
        self.ui.BtnHome.Click += self._go_home
        self.ui.BtnBookmark.Click += self._toggle_bookmark
        self.ui.MarkdownBrowser.Navigating += self._on_browser_navigating
        self.ui.SearchBox.TextChanged += lambda sender, args: self.search_mode and self._run_search(sender.Text)
        self.ui.BtnClearSearch.Click += lambda sender, args: self._clear_search()
        ui_notify.register_theme_listener(self._theme_changed)

    def _on_window_loaded(self, sender, args):
        self._load_tree()
        self._search_selected(None, None)

    def _get_panel_grid(self):
        try:
            return self.ui.DocumentTree.Parent.Parent
        except Exception:
            return None

    def _restore_panel_widths(self):
        grid = self._get_panel_grid()
        if grid is None:
            return
        try:
            values = config.load()
            left = float(values.get("help_left_panel_width", 0))
            right = float(values.get("help_right_panel_width", 0))
            if left > 0:
                grid.ColumnDefinitions[0].Width = GridLength(
                    left, GridUnitType.Pixel)
            if right > 0:
                grid.ColumnDefinitions[4].Width = GridLength(
                    right, GridUnitType.Pixel)
        except Exception:
            pass

    def _save_panel_widths(self):
        grid = self._get_panel_grid()
        if grid is None:
            return
        try:
            left = float(grid.ColumnDefinitions[0].ActualWidth)
            right = float(grid.ColumnDefinitions[4].ActualWidth)
            if left > 0:
                config.set_value("help_left_panel_width", left)
            if right > 0:
                config.set_value("help_right_panel_width", right)
        except Exception:
            pass

    def _on_window_closing(self, sender, args):
        self._save_panel_widths()

    def _on_window_closed(self, sender, args):
        ui_notify.unregister_theme_listener(self._theme_changed)
        if HelpDialog._active_instance is self:
            HelpDialog._active_instance = None
        self.win = None
        self.ui = None

    def show(self):
        i18n.init_from_config()
        self._init_window()
        self.win.Loaded += self._on_window_loaded
        self.win.Closed += self._on_window_closed
        HelpDialog._active_instance = self
        self.win.Show()


def _show_help():
    active = HelpDialog._active_instance
    if active is not None and active.win is not None:
        if active.win.WindowState == WindowState.Minimized:
            active.win.WindowState = WindowState.Normal
        active.win.Activate()
        return
    HelpDialog().show()


_show_help()
