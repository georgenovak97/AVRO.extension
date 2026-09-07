# -*- coding: utf-8 -*-
"""Small dependency-free Markdown renderer suitable for Obsidian notes."""
import base64
import os
import re

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote


def _escape(value):
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _web_safe(value):
    """Remove unpaired UTF-16 surrogates rejected by WPF WebBrowser."""
    if not value:
        return value
    result = []
    index = 0
    while index < len(value):
        code = ord(value[index])
        if 0xD800 <= code <= 0xDBFF:
            if (index + 1 < len(value) and
                    0xDC00 <= ord(value[index + 1]) <= 0xDFFF):
                result.extend((value[index], value[index + 1]))
                index += 2
                continue
            index += 1
            continue
        if 0xDC00 <= code <= 0xDFFF:
            index += 1
            continue
        result.append(value[index])
        index += 1
    return "".join(result)


def _file_url(path):
    path = os.path.abspath(path).replace("\\", "/")
    return "file:///{}".format("/".join(
        _url_quote(part, safe=":") for part in path.split("/")))


def _data_url(path):
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
    with open(path, "rb") as stream:
        encoded = base64.b64encode(stream.read())
    try:
        encoded = encoded.decode("ascii")
    except AttributeError:
        pass
    return "data:{};base64,{}".format(mime, encoded)


def _url_quote(value, safe=""):
    try:
        return quote(value.encode("utf-8"), safe=safe)
    except (AttributeError, TypeError):
        return quote(value, safe=safe)


def _decode_html(value):
    return value.replace("&quot;", '"').replace("&gt;", ">") \
        .replace("&lt;", "<").replace("&amp;", "&")


def _image_src(source, base_path, root_path):
    source = _decode_html(source).replace("\\", os.sep)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", source):
        return source

    candidates = []
    if os.path.isabs(source):
        candidates.append(source)
    else:
        base = os.path.abspath(base_path) if base_path else ""
        root = os.path.abspath(root_path) if root_path else ""
        if not root and base:
            current = base
            while current and current != os.path.dirname(current):
                if os.path.isdir(os.path.join(current, ".obsidian")):
                    root = current
                    break
                current = os.path.dirname(current)
        if base:
            candidates.append(os.path.join(base, source))
        if root:
            candidates.append(os.path.join(root, "attachments", source))
            candidates.append(os.path.join(root, source))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return _data_url(candidate)

    return "/".join(_url_quote(part, safe=":")
                    for part in source.replace("\\", "/").split("/"))


def _inline(value, base_path="", root_path=""):
    # Obsidian escapes punctuation in headings and list-like text.
    value = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~<>])", r"\1", value)
    spans = []

    def protect_span(match):
        spans.append(match.group(0))
        return "@@AVROSPAN{}TOKEN@@".format(len(spans) - 1)

    value = re.sub(r"<span\s+style\s*=\s*([\"'])([^\"']*)\1\s*>",
                   lambda match: protect_span(match), value,
                   flags=re.IGNORECASE)
    value = re.sub(r"</span\s*>", protect_span, value, flags=re.IGNORECASE)
    value = re.sub(r"<u\s*>", protect_span, value, flags=re.IGNORECASE)
    value = re.sub(r"</u\s*>", protect_span, value, flags=re.IGNORECASE)
    value = _escape(value)
    value = re.sub(r"!\[\[([^]|]+)(?:\|([^]]+))?\]\]",
                   lambda m: '<img alt="{}" src="{}">'.format(
                       m.group(2) or m.group(1),
                       _image_src(m.group(1), base_path, root_path)), value)
    value = re.sub(r"!\[([^]]*)\]\(([^)]+)\)",
                   lambda m: '<img alt="{}" src="{}">'.format(
                       m.group(1), _image_src(m.group(2), base_path, root_path)),
                   value)
    value = re.sub(r"\[([^]]+)\]\(([^)]+)\)",
                   r'<a href="\2">\1</a>', value)
    value = re.sub(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]",
                   lambda m: '<span class="wikilink">{}</span>'.format(
                       m.group(2) or m.group(1)), value)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"==(.+?)==", r'<span class="highlight">\1</span>', value)
    value = re.sub(r"\*\*(.+?)\*\*|__(.+?)__",
                   lambda m: "<strong>{}</strong>".format(m.group(1) or m.group(2)), value)
    value = re.sub(r"~~(.+?)~~", r"<del>\1</del>", value)
    value = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\w)|(?<![_\w])_([^_]+)_(?!\w)",
                   lambda m: "<em>{}</em>".format(m.group(1) or m.group(2)), value)
    for index, span in enumerate(spans):
        lower = span.lower()
        if lower.startswith("</span"):
            replacement = "</span>"
        elif lower.startswith("<u"):
            replacement = "<u>"
        elif lower.startswith("</u"):
            replacement = "</u>"
        else:
            style = re.search(r"style\s*=\s*([\"'])([^\"']*)\1", span,
                              flags=re.IGNORECASE).group(2)
            replacement = '<span style="{}">'.format(_escape(style))
        value = value.replace("@@AVROSPAN{}TOKEN@@".format(index), replacement)
    return value


def _slug(value):
    return re.sub(r"[^a-z0-9а-яё]+", "-", value.lower()).strip("-")


def _table_row(line):
    value = line.strip()
    if not value.startswith("|") or not value.endswith("|"):
        return None
    return [cell.strip() for cell in value[1:-1].split("|")]


def _is_separator(cells):
    return bool(cells) and all(re.match(r"^:?-+:?$", cell) for cell in cells)


def _render_table(rows, base_path="", root_path=""):
    if len(rows) < 2 or _is_separator(rows[0]):
        return ""
    has_header = _is_separator(rows[1])
    header = rows[0] if has_header else []
    body = rows[2:] if has_header else rows
    result = ["<table>"]
    if header:
        result.append("<thead><tr>{}</tr></thead>".format(
            "".join("<th>{}</th>".format(_inline(cell, base_path, root_path))
                    for cell in header)))
    result.append("<tbody>")
    for row in body:
        result.append("<tr>{}</tr>".format(
            "".join("<td>{}</td>".format(
                _inline(cell, base_path, root_path)) for cell in row)))
    result.append("</tbody></table>")
    return "".join(result)


def markdown_to_html(text, title="", base_path="", scroll_to="", root_path=""):
    lines = (text or "").replace("\r\n", "\n").split("\n")
    html = []
    index = 0
    in_code = False
    code = []
    list_type = None
    list_class = None
    while index < len(lines):
        line = lines[index]
        fence = re.match(r"^\s*(```|~~~)\s*(.*)$", line)
        if fence:
            if in_code:
                html.append("<pre><code>{}</code></pre>".format(_escape("\n".join(code))))
                code = []
                in_code = False
            else:
                if list_type:
                    html.append("</ol>" if list_type == "ol" else "</ul>")
                    list_type = None
                    list_class = None
                in_code = True
            index += 1
            continue
        if in_code:
            code.append(line)
            index += 1
            continue

        cells = _table_row(line)
        if cells is not None:
            rows = []
            while index < len(lines) and _table_row(lines[index]) is not None:
                rows.append(_table_row(lines[index]))
                index += 1
            table = _render_table(rows, base_path, root_path)
            if table:
                html.append(table)
            continue

        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            if list_type:
                html.append("</ol>" if list_type == "ol" else "</ul>")
                list_type = None
                list_class = None
            level = len(heading.group(1))
            value = heading.group(2).strip()
            html.append('<h{0} id="{1}">{2}</h{0}>'.format(
                level, _slug(value), _inline(value, base_path, root_path)))
            index += 1
            continue
        if re.match(r"^\s*[-*_](\s*[-*_]){2,}\s*$", line):
            html.append("<hr>")
            index += 1
            continue

        task = re.match(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.+)$", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        bulleted = re.match(r"^\s*[-*+]\s+(.+)$", line)
        if task or numbered or bulleted:
            wanted = "ol" if numbered else "ul"
            wanted_class = "task-list" if task else None
            if list_type != wanted or list_class != wanted_class:
                if list_type:
                    html.append("</ol>" if list_type == "ol" else "</ul>")
                html.append("<ul class=\"task-list\">" if wanted_class
                             else "<{}>".format(wanted))
                list_type = wanted
                list_class = wanted_class
            if task:
                checked = " checked" if task.group(1) != " " else ""
                html.append('<li><input type="checkbox" disabled{}> {}</li>'.format(
                    checked, _inline(task.group(2), base_path, root_path)))
            else:
                html.append("<li>{}</li>".format(_inline(
                    (numbered or bulleted).group(1), base_path, root_path)))
            index += 1
            continue
        if list_type:
            html.append("</ol>" if list_type == "ol" else "</ul>")
            list_type = None
            list_class = None
        quote = re.match(r"^\s*>\s*(.*)$", line)
        if quote:
            callout = re.match(r"\[!(\w+)\]\s*(.*)$", quote.group(1))
            if callout:
                html.append('<div class="callout {}"><b>{}</b><br>{}</div>'.format(
                    callout.group(1).lower(), callout.group(1).title(),
                    _inline(callout.group(2), base_path, root_path)))
            else:
                html.append("<blockquote>{}</blockquote>".format(_inline(
                    quote.group(1), base_path, root_path)))
            index += 1
            continue
        if line.strip():
            html.append("<p>{}</p>".format(_inline(line, base_path, root_path)))
        index += 1
    if list_type:
        html.append("</ol>" if list_type == "ol" else "</ul>")
    if in_code:
        html.append("<pre><code>{}</code></pre>".format(_escape("\n".join(code))))
    base = ""
    if base_path:
        base = '<base href="file:///{}/">'.format(
            base_path.replace("\\", "/").replace(" ", "%20").rstrip("/"))
    scroll_script = ""
    if scroll_to:
        scroll_script = (
            "<script>var _tc=!1;window.onload=function(){"
            "var e=document.getElementById('" + scroll_to + "');"
            "if(e)e.scrollIntoView();setTimeout(function(){_tc=!0},250);"
            "};window.onscroll=function(){if(_tc){_tc=!1;"
            "window.location='help://toc-clearselection'}}</script>"
        )
    return """<!doctype html><html><head><meta charset="utf-8">@@base@@<style>
body{font-family:'Segoe UI',Arial,sans-serif;background:@@bg@@;color:@@text@@;margin:26px 34px;line-height:1.45;font-size:14px}
h1,h2,h3,h4,h5,h6{color:@@text@@;font-weight:600;margin:1.15em 0 .45em}h1{font-size:28px}h2{font-size:22px}h3{font-size:18px}
 p{margin:.55em 0}ol,ul{margin:8px 0;padding-left:26px}li{margin:1px 0;line-height:1.35}.task-list{list-style:none;padding-left:0}.task-list li{margin-left:0}.task-list input{margin-right:6px;width:14px;height:14px;vertical-align:middle}a{color:@@link@@}code,pre,blockquote{background:@@codebg@@}code{padding:2px 5px;border-radius:3px}pre{padding:14px;overflow:auto;border-left:3px solid @@link@@}blockquote{border-left:4px solid @@link@@;margin:12px 0;padding:4px 14px}.highlight{background:#d9b44a;padding:0 2px;border-radius:2px}.wikilink{color:@@link@@}img{max-width:100%}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:13px}th,td{border:1px solid @@border@@;padding:7px 10px;text-align:left;vertical-align:top}th{background:@@codebg@@;font-weight:600}.callout{padding:10px 14px;margin:12px 0;border-left:4px solid @@link@@;background:@@codebg@@}
</style></head><body>@@content@@@@scroll@@</body></html>""".replace(
        "@@base@@", base).replace("@@content@@", "\n".join(html)).replace(
        "@@scroll@@", scroll_script)


def themed_html(text, palette, title="", base_path="", scroll_to="", root_path=""):
    html = markdown_to_html(text, title, base_path, scroll_to, root_path)
    for key, value in (("bg", palette["BgPanel"]), ("text", palette["TextMain"]),
                       ("link", palette["SelBorder"]), ("codebg", palette["BgToolbar"]),
                       ("border", palette["BorderLight"])):
        html = html.replace("@@" + key + "@@", value)
    return _web_safe(html)


def search_results_html(results, query, palette, title="Search", no_results="No matching documents.", count_label="Documents found: {n}"):
    """Render the Help home page search results with the shared palette."""
    if not (query or "").strip():
        return themed_html("", palette)
    query = _escape(query or "")
    blocks = []
    if not results:
        blocks.append("<p class=\"empty\">{}</p>".format(_escape(no_results)))
    else:
        blocks.append("<p class=\"count\">{}</p>".format(
            _escape(count_label.format(n=len(results)))))
        for path, snippet in results:
            href = path.replace("\\", "/").replace(" ", "%20")
            blocks.append("<div class=\"search-result\"><a href=\"help://open?path={0}\">{1}</a><p>{2}</p></div>".format(
                _escape(href), _escape(os.path.splitext(os.path.basename(path))[0]),
                _inline(snippet)))

    html = markdown_to_html("", base_path="")
    html = html.replace("</style>", ".count{font-weight:600}.search-result{display:block;font-size:12px;padding:4px 0;margin:0}.search-result a{font-size:12px;font-weight:600;text-decoration:none}.search-result p{font-size:11px;margin:3px 0 0}</style>")
    html = html.replace("<body></body>", "<body>{}</body>".format("\n".join(blocks)))
    for key, value in (("bg", palette["BgPanel"]), ("text", palette["TextMain"]),
                       ("link", palette["SelBorder"]), ("codebg", palette["BgToolbar"]),
                       ("border", palette["BorderLight"])):
        html = html.replace("@@" + key + "@@", value)
    return _web_safe(html)


def home_page_html(bookmarks, recent, palette, bookmarks_title,
                   recent_title, bookmarks_empty, recent_empty):
    """Render the Help home page with bookmarks and recent documents."""
    def section(title, paths, empty):
        blocks = ["<div class=\"home-section\"><h2>{}</h2>".format(
            _escape(title))]
        if not paths:
            blocks.append("<p class=\"empty\">{}</p>".format(_escape(empty)))
        else:
            for path in paths:
                href = path.replace("\\", "/").replace(" ", "%20")
                blocks.append(
                    "<div class=\"search-result\"><a href=\"help://open?path={0}\">{1}</a></div>".format(
                        _escape(href),
                        _escape(os.path.splitext(os.path.basename(path))[0])))
        blocks.append("</div>")
        return blocks

    blocks = section(bookmarks_title, bookmarks, bookmarks_empty)
    blocks.extend(section(recent_title, recent, recent_empty))
    html = markdown_to_html("", base_path="")
    html = html.replace(
        "</style>",
        ".home-section h2{font-size:13px;margin:0 0 8px}.home-section{display:block;margin-bottom:24px}"
        ".search-result{display:block;font-size:12px;padding:4px 0;margin:0}"
        ".search-result a{font-size:12px;font-weight:600;text-decoration:none}</style>")
    html = html.replace("<body></body>", "<body>{}</body>".format(
        "\n".join(blocks)))
    for key, value in (("bg", palette["BgPanel"]), ("text", palette["TextMain"]),
                       ("link", palette["SelBorder"]), ("codebg", palette["BgToolbar"]),
                       ("border", palette["BorderLight"])):
        html = html.replace("@@" + key + "@@", value)
    return _web_safe(html)


def recent_results_html(results, palette):
    """Render recently viewed documents without a search header."""
    pairs = [(path, "") for path in results]
    return search_results_html(pairs, "recent", palette,
                               no_results="", count_label="")
