"""A very small Markdown to HTML converter for the legal texts (headings, paragraphs, lists, bold, code, links).

It escapes all HTML first, so a text can never add markup of its own. It exists so that no extra package is needed.
"""

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]*)\)")
_BARE = re.compile(r"(?<![\"'>(])\b(https?://[^\s<)]+)")


def _inline(text: str) -> str:
    out = escape(text)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _LINK.sub(r'<a href="\2">\1</a>', out)
    out = _BARE.sub(r'<a href="\1">\1</a>', out)
    return out


def render(source: str):
    html, paragraph, items = [], [], []

    def flush_paragraph():
        if paragraph:
            html.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def flush_list():
        if items:
            html.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in source.splitlines():
        stripped = line.strip()
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            html.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif stripped.startswith(("- ", "* ")):
            flush_paragraph()
            items.append(stripped[2:].strip())
        elif not stripped:
            flush_paragraph()
            flush_list()
        elif items and line.startswith("  "):
            items[-1] += " " + stripped  # a wrapped list item
        else:
            flush_list()
            paragraph.append(stripped)
    flush_paragraph()
    flush_list()
    return mark_safe("\n".join(html))  # noqa: S308  everything was escaped above
