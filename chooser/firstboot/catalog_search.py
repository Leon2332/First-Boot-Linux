"""Live search over the Other options catalog.

The GTK list only materializes visible rows. This module is the cheap part:
precomputed casefolded fields and an incremental AND-of-tokens scan that
stays linear in the current hit list, not in widget count. Five thousand
short strings is a sub-millisecond pass.

A token matches a distro if it is a substring of the display name
(catalog_name / name: Ubuntu, Fedora, Linux Mint, Microsoft Windows).
Ids, versions, desktop/edition names, taglines, and descriptions are
not searched — "plasma" must not hit Fedora, "v" must not hit Lubuntu.
"""

from __future__ import annotations

from typing import Generic, Sequence, TypeVar

from firstboot.payload import Distro

T = TypeVar("T")

MORE_STRICT = "more_strict"
LESS_STRICT = "less_strict"
DIFFERENT = "different"
SAME = "same"

Fields = tuple[str, ...]


def fields(distro: Distro) -> Fields:
    parts = [distro.catalog_name, distro.name]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        key = part.casefold()
        if part and key not in seen:
            seen.add(key)
            out.append(key)
    return tuple(out)


def tokens(query: str) -> tuple[str, ...]:
    return tuple(query.casefold().split())


def matches(fields: Sequence[str], query_tokens: tuple[str, ...]) -> bool:
    if not query_tokens:
        return True
    if isinstance(fields, str):
        fields = (fields,)
    return all(
        any(token in field for field in fields) for token in query_tokens
    )


def filter_delta(old: str, new: str) -> str:
    """How ``new`` relates to ``old`` for Gtk.FilterChange.

    Adding characters (or tokens) at the end is MORE_STRICT, so a
    FilterListModel can skip rows that already failed. Deleting is
    LESS_STRICT. Anything else is a full rescan.
    """
    old_j = " ".join(tokens(old))
    new_j = " ".join(tokens(new))
    if old_j == new_j:
        return SAME
    if new_j.startswith(old_j):
        return MORE_STRICT
    if old_j.startswith(new_j):
        return LESS_STRICT
    return DIFFERENT


class SearchIndex(Generic[T]):
    """Sorted (item, fields) list with incremental narrowing."""

    __slots__ = ("_all", "_query", "_hits")

    def __init__(self, items: Sequence[tuple[T, Sequence[str]]]) -> None:
        self._all = tuple((item, tuple(flds)) for item, flds in items)
        self._query = ""
        self._hits = self._all

    def __len__(self) -> int:
        return len(self._all)

    @property
    def items(self) -> tuple[tuple[T, Fields], ...]:
        return self._all

    def search(self, query: str) -> list[T]:
        query_tokens = tokens(query)
        joined = " ".join(query_tokens)
        if not query_tokens:
            self._query = ""
            self._hits = self._all
            return [item for item, _fields in self._all]
        source = (
            self._hits
            if self._query and joined.startswith(self._query)
            else self._all
        )
        hits = tuple(
            (item, flds)
            for item, flds in source
            if matches(flds, query_tokens)
        )
        self._query = joined
        self._hits = hits
        return [item for item, _fields in hits]


def catalog_index(distros: Sequence[Distro]) -> SearchIndex[Distro]:
    ordered = sorted(distros, key=lambda d: (d.catalog_name.casefold(), d.id))
    return SearchIndex([(distro, fields(distro)) for distro in ordered])
