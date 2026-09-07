# -*- coding: utf-8 -*-
"""Apply AVRO ribbon labels and pyRevit-style tooltips from Revit UI language."""
from __future__ import print_function

from revit_utils import as_unicode

_BRAILLE_PANEL = u"\u2800"
_PYREVIT_TAB_KEY = u"AVRO"
_PYREVIT_TOOLS_PANEL_KEY = u"Tools"
_RIBBON_AUTHOR = u"AVRO Consulting"

# Revit internal command names (see pyRevit Bundle Name footer).
_BUNDLE_SETTINGS = u"Settings"
_BUNDLE_FAMILY_BROWSER = u"FamilyBrowser"  # matches FamilyBrowser.pushbutton folder
_BUNDLE_HELP = u"Help"


def tab_has_avro_settings_panel(tab):
    """True if tab contains AVRO ``01_Settings`` panel (braille blank title)."""
    if tab is None:
        return False
    try:
        for panel in tab.Panels:
            src = getattr(panel, "Source", None)
            if src is None:
                continue
            if as_unicode(getattr(src, "Title", None) or u"") == _BRAILLE_PANEL:
                return True
    except Exception:
        pass
    return False


def _tab_has_bundle(tab, bundle_name):
    if tab is None or not bundle_name:
        return False
    try:
        for panel in tab.Panels:
            for item in _walk_items(panel):
                pb = _get_revit_pushbutton(item)
                if pb is None:
                    continue
                if as_unicode(getattr(pb, "Name", None)) == bundle_name:
                    return True
    except Exception:
        pass
    return False


def find_avro_tab():
    """Return the AVRO ribbon tab, or None (never the core pyRevit tab)."""
    try:
        import clr
        clr.AddReference("AdWindows")
        from Autodesk.Windows import ComponentManager
    except Exception:
        return None
    try:
        for tab in ComponentManager.Ribbon.Tabs:
            if tab is None:
                continue
            if tab_has_avro_settings_panel(tab):
                return tab
            if (_tab_has_bundle(tab, _BUNDLE_SETTINGS)
                    and _tab_has_bundle(tab, _BUNDLE_FAMILY_BROWSER)):
                return tab
    except Exception:
        pass
    return None


def _is_text(value):
    try:
        basestring
        return isinstance(value, basestring)
    except NameError:
        return isinstance(value, (str, unicode))


def _texts_for_key(key):
    import i18n
    return set(
        i18n.t(key, lang=lng)
        for lng in (u"ru", u"en")
    )


def _pyrevit_tooltip_body(description, bundle_name, author=_RIBBON_AUTHOR):
    """Same layout as pyRevit ``_make_button_tooltip`` (description + bundle + author)."""
    body = as_unicode(description).strip()
    if body:
        body += u"\n\n"
    body += u"Bundle Name:\n{} (pushbutton)".format(
        bundle_name or u"AVRO")
    if author:
        body += u"\n\nAuthor(s):\n{}".format(author)
    return body


def _get_revit_pushbutton(item):
    """Revit ``PushButton`` from AdWindows ribbon item (reflection)."""
    try:
        from Autodesk.Revit.UI import PushButton
        import System.Reflection as rf
    except Exception:
        return None

    for host in (item, getattr(item, "Source", None)):
        if host is None:
            continue
        try:
            rvt = getattr(host, "GetRevitItem", None)
            if rvt is not None:
                pb = rvt()
                if isinstance(pb, PushButton):
                    return pb
        except Exception:
            pass
        try:
            get_item = host.GetType().GetMethod(
                "getRibbonItem",
                rf.BindingFlags.NonPublic | rf.BindingFlags.Instance,
            )
            if get_item is not None:
                pb = get_item.Invoke(host, None)
                if isinstance(pb, PushButton):
                    return pb
        except Exception:
            pass
    return None


def _find_avro_pyrvt_tab():
    """pyRevit UI tree for AVRO tab (Settings + FamilyBrowser)."""
    try:
        from pyrevit.coreutils import ribbon
        ui = ribbon.get_current_ui()
        for tab in ui.get_pyrevit_tabs():
            if (tab.find_child(_BUNDLE_SETTINGS) is not None
                    and tab.find_child(_BUNDLE_FAMILY_BROWSER) is not None):
                return tab
    except Exception:
        pass
    return None


def _apply_buttons_via_pyrevit(pyrvt_tab, specs):
    """Update tooltips through pyRevit (same path as bundle reload)."""
    updated = False
    for bundle_name, title, description in specs:
        btn = pyrvt_tab.find_child(bundle_name)
        if btn is None:
            continue
        full_tip = _pyrevit_tooltip_body(description, bundle_name)
        try:
            btn.set_title(title)
            btn.set_tooltip(full_tip)
            btn.set_tooltip_ext(u"")
            updated = True
        except Exception:
            pass
    return updated


def _tip_matches(tip, variants):
    if not tip:
        return False
    if tip in variants:
        return True
    for variant in variants:
        if variant and variant in tip:
            return True
    return False


def _read_tooltip_text(item, pb=None):
    if pb is None:
        pb = _get_revit_pushbutton(item)
    if pb is not None:
        try:
            tip = pb.ToolTip
            if _is_text(tip) and tip:
                return as_unicode(tip)
        except Exception:
            pass
    if item is None:
        return u""
    try:
        tip = item.ToolTip
    except Exception:
        return u""
    if tip is None:
        return u""
    if _is_text(tip):
        return as_unicode(tip)
    try:
        content = getattr(tip, "Content", None)
        if content:
            return as_unicode(content)
    except Exception:
        pass
    return u""


def _set_item_label(item, text):
    if item is None or not text:
        return
    try:
        if hasattr(item, "Text"):
            item.Text = text
    except Exception:
        pass
    try:
        src = getattr(item, "Source", None)
        if src is not None and hasattr(src, "Title"):
            src.Title = text
    except Exception:
        pass
    pb = _get_revit_pushbutton(item)
    if pb is not None:
        try:
            pb.ItemText = text
        except Exception:
            pass


def _set_adwindows_tooltip(item, title, full_tip):
    """Replace cached ``RibbonToolTip`` so Revit shows new description text."""
    try:
        import clr
        clr.AddReference("AdWindows")
        import Autodesk.Windows as AdWindows
    except Exception:
        return
    title_u = as_unicode(title)
    for host in (item, getattr(item, "Source", None)):
        if host is None:
            continue
        try:
            host.ToolTip = AdWindows.RibbonToolTip()
            host.ToolTip.Title = title_u
            host.ToolTip.Content = full_tip
            resolve = getattr(host, "ResolveToolTip", None)
            if resolve is not None:
                resolve()
        except Exception:
            pass


def _set_item_pyrevit_tooltip(item, title, description, bundle_name):
    """pyRevit-style tooltip on Revit API + fresh AdWindows ``RibbonToolTip``."""
    if item is None:
        return
    pb = _get_revit_pushbutton(item)
    name = bundle_name
    if not name and pb is not None:
        try:
            name = as_unicode(pb.Name)
        except Exception:
            name = u""
    if not name:
        name = as_unicode(title).strip().replace(u" ", u"") or u"AVRO"
    title_u = as_unicode(title)
    full_tip = _pyrevit_tooltip_body(description, name)

    if pb is not None:
        try:
            pb.ToolTip = full_tip
        except Exception:
            pass
        try:
            pb.LongDescription = u""
        except Exception:
            pass

    _set_adwindows_tooltip(item, title_u, full_tip)


def _walk_items(container):
    if container is None:
        return
    items = getattr(container, "Items", None)
    if items is None:
        src = getattr(container, "Source", None)
        items = getattr(src, "Items", None) if src is not None else None
    if items is None:
        return
    try:
        count = items.Count
    except Exception:
        count = len(items)
    for i in range(count):
        try:
            it = items[i]
        except Exception:
            continue
        if it is None:
            continue
        sub = getattr(it, "Items", None)
        if sub is not None:
            try:
                if sub.Count > 0:
                    _walk_items(it)
                    continue
            except Exception:
                pass
        yield it


def _find_tab_by_display_titles():
    """Fallback when Settings panel is not built yet (early startup)."""
    try:
        import clr
        clr.AddReference("AdWindows")
        from Autodesk.Windows import ComponentManager
    except Exception:
        return None
    titles = _texts_for_key("tab_title") | {_PYREVIT_TAB_KEY, u"AVRO"}
    try:
        for tab in ComponentManager.Ribbon.Tabs:
            if tab is None:
                continue
            if as_unicode(getattr(tab, "Title", None) or u"") in titles:
                return tab
    except Exception:
        pass
    return None


def prepare_match_keys():
    """
    Reset tab/panel keys before pyRevit ``update_pyrevit_ui``.

    pyRevit matches the Tools panel by bundle title (``Tools``). After
    ``apply()``, titles may be localized; this restores match keys on reload.
    """
    tab = find_avro_tab() or _find_tab_by_display_titles()
    if tab is None:
        return False
    panel_keys = _texts_for_key("ribbon_panel_tools") | {_PYREVIT_TOOLS_PANEL_KEY}
    try:
        tab.Title = _PYREVIT_TAB_KEY
    except Exception:
        pass
    try:
        for panel in tab.Panels:
            src = getattr(panel, "Source", None)
            if src is None:
                continue
            ptitle = as_unicode(getattr(src, "Title", None) or u"")
            if ptitle == _BRAILLE_PANEL:
                continue
            if ptitle in panel_keys:
                try:
                    src.Title = _PYREVIT_TOOLS_PANEL_KEY
                except Exception:
                    pass
    except Exception:
        pass
    return True


def ribbon_ui_ready():
    """True when AVRO ribbon exists (AdWindows tab or pyRevit UI tree)."""
    if find_avro_tab() is not None:
        return True
    return _find_avro_pyrvt_tab() is not None


def has_family_browser_button():
    """True if Family Browser pushbutton exists on the AVRO ribbon."""
    pyrvt_tab = _find_avro_pyrvt_tab()
    if pyrvt_tab is not None:
        try:
            if pyrvt_tab.find_child(_BUNDLE_FAMILY_BROWSER) is not None:
                return True
        except Exception:
            pass
    tab = find_avro_tab()
    if tab is None:
        return False
    try:
        for panel in tab.Panels:
            for item in _walk_items(panel):
                pb = _get_revit_pushbutton(item)
                if pb is not None and as_unicode(pb.Name) == _BUNDLE_FAMILY_BROWSER:
                    return True
    except Exception:
        pass
    return False


def _apply_tools_panel_display(tab, tools_display):
    """Localized panel caption (internal key stays ``Tools`` for pyRevit Reload)."""
    if tab is None or not tools_display:
        return
    keys = _texts_for_key("ribbon_panel_tools") | {_PYREVIT_TOOLS_PANEL_KEY}
    try:
        for panel in tab.Panels:
            src = getattr(panel, "Source", None)
            if src is None:
                continue
            ptitle = as_unicode(getattr(src, "Title", None) or u"")
            if ptitle == _BRAILLE_PANEL:
                continue
            if ptitle in keys:
                try:
                    src.Title = as_unicode(tools_display)
                except Exception:
                    pass
    except Exception:
        pass


def apply(lang=None):
    """Update tab, panel, button captions, and pyRevit-style tooltips."""
    try:
        import config
        import i18n
    except Exception:
        return False

    lng = lang or config.read_ui_language()
    i18n.set_language(lng)

    settings_names = _texts_for_key("settings_dialog_title")
    settings_tips = _texts_for_key("settings_ribbon_tooltip")
    fm_names = _texts_for_key("ribbon_title") | {
        u"\u0411\u0440\u0430\u0443\u0437\u0435\u0440 \u0441\u0435\u043c\u0435\u0439\u0441\u0442\u0432",
        u"Family Manager",
    }
    fm_tips = _texts_for_key("ribbon_tooltip")
    help_names = _texts_for_key("help_ribbon_title")
    help_tips = _texts_for_key("help_ribbon_tooltip")

    new_tab = i18n.t("tab_title")
    new_settings = i18n.t("settings_dialog_title")
    new_settings_tip = i18n.t("settings_ribbon_tooltip")
    new_fm = i18n.t("ribbon_title")
    new_fm_tip = i18n.t("ribbon_tooltip")
    new_help = i18n.t("help_ribbon_title")
    new_help_tip = i18n.t("help_ribbon_tooltip")

    tab = find_avro_tab()
    pyrvt_tab = _find_avro_pyrvt_tab()
    if tab is None and pyrvt_tab is None:
        return False

    updated = False
    try:
        if tab is not None:
            tab.Title = new_tab
            _apply_tools_panel_display(tab, i18n.t("ribbon_panel_tools"))
            updated = True
        if pyrvt_tab is not None:
            if _apply_buttons_via_pyrevit(
                    pyrvt_tab, (
                        (_BUNDLE_SETTINGS, new_settings, new_settings_tip),
                        (_BUNDLE_FAMILY_BROWSER, new_fm, new_fm_tip),
                        (_BUNDLE_HELP, new_help, new_help_tip),
                    )):
                updated = True
        if tab is None:
            return updated
        for panel in tab.Panels:
            src = getattr(panel, "Source", None)
            if src is None:
                continue
            for item in _walk_items(panel):
                label = u""
                try:
                    label = item.Text or u""
                except Exception:
                    pass
                if not label:
                    try:
                        label = item.Source.Title or u""
                    except Exception:
                        label = u""
                pb = _get_revit_pushbutton(item)
                tip = _read_tooltip_text(item, pb)
                bundle_id = u""
                if pb is not None:
                    try:
                        bundle_id = as_unicode(pb.Name)
                    except Exception:
                        bundle_id = u""
                if (bundle_id == _BUNDLE_SETTINGS
                        or label in settings_names
                        or _tip_matches(tip, settings_tips)):
                    _set_item_label(item, new_settings)
                    _set_item_pyrevit_tooltip(
                        item, new_settings, new_settings_tip,
                        _BUNDLE_SETTINGS)
                elif (bundle_id == _BUNDLE_FAMILY_BROWSER
                        or label in fm_names
                        or _tip_matches(tip, fm_tips)):
                    _set_item_label(item, new_fm)
                    _set_item_pyrevit_tooltip(
                        item, new_fm, new_fm_tip,
                        _BUNDLE_FAMILY_BROWSER)
                elif (bundle_id == _BUNDLE_HELP
                        or label in help_names
                        or _tip_matches(tip, help_tips)):
                    _set_item_label(item, new_help)
                    _set_item_pyrevit_tooltip(
                        item, new_help, new_help_tip, _BUNDLE_HELP)
    except Exception:
        return False
    return updated


def init_from_config():
    try:
        import config
        return apply(config.read_ui_language())
    except Exception:
        return False
