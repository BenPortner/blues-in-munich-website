"""Small BeautifulSoup helpers shared by HTML adapters."""
from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag

from ..models import clean_text


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def text(node: Tag | None, sep: str = " ") -> str:
    return clean_text(node.get_text(sep)) if node else ""


def text_until(start: Tag, stop_names: tuple[str, ...]) -> str:
    """Text of everything after `start` up to the next tag named in `stop_names`."""
    parts = []
    for el in start.next_elements:
        if isinstance(el, Tag) and el.name in stop_names and el is not start:
            break
        if isinstance(el, NavigableString) and el.parent.name not in ("script", "style"):
            if start not in el.parents:
                parts.append(str(el))
    return clean_text(" ".join(parts))
