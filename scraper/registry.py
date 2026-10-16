"""Adapter registry. An adapter is `fn(source: dict, ctx: Context) -> list[Event]`.

Adapters return every event they find; the runner applies the blues filter.
An empty result normally means the page layout changed and counts as a failure;
API adapters register with `allow_empty=True` because "no matches" is a valid answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from .http import Http

ADAPTERS: dict[str, Callable] = {}


class SkipSource(Exception):
    """Raised when a source can't run by design (e.g. missing API key)."""


@dataclass
class Context:
    http: Http
    today: date = field(default_factory=date.today)
    root: Path = Path(".")


def adapter(name: str, allow_empty: bool = False):
    def register(fn):
        fn.allow_empty = allow_empty
        ADAPTERS[name] = fn
        return fn
    return register


def get_adapter(name: str) -> Callable:
    from . import adapters  # noqa: F401  (imports register every adapter)
    try:
        return ADAPTERS[name]
    except KeyError:
        raise KeyError(f"unknown adapter '{name}'; known: {sorted(ADAPTERS)}") from None
