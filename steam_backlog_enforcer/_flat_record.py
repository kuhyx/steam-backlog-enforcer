"""Nested dataclass groups stored as one flat JSON object.

The persisted records (``config.json``, ``state.json``, the playtime state)
are flat JSON objects that older daemons and kuhy's hand edits rely on. In
code, related fields live in a nested dataclass, a *group*, so no record
carries more than pylint's ``max-attributes``. A group field is marked with
:func:`flat_group`; :func:`to_flat` writes its fields inline (with an
optional key prefix) at the group's position, and :func:`from_flat` reads
them back, so the bytes on disk do not change.
"""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Any, ClassVar, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

_GROUP: Final = "flat_group"


class DataclassInstance(Protocol):
    """Any dataclass instance (what ``dataclasses.fields`` accepts)."""

    __dataclass_fields__: ClassVar[dict[str, Any]]


def flat_group(cls: type[DataclassInstance], prefix: str = "") -> dict[str, Any]:
    """Field metadata marking a group of *cls*, stored with key *prefix*."""
    return {_GROUP: (cls, prefix)}


def _group_of(meta: Mapping[str, Any]) -> tuple[type[DataclassInstance], str] | None:
    """The group's class and key prefix, or ``None`` for a plain field."""
    group: tuple[type[DataclassInstance], str] | None = meta.get(_GROUP)
    return group


def to_flat(record: DataclassInstance) -> dict[str, Any]:
    """The record's fields as one flat dict, groups inlined in place."""
    out: dict[str, Any] = {}
    for f in fields(record):
        value = getattr(record, f.name)
        group = _group_of(f.metadata)
        if group is None:
            out[f.name] = value
        else:
            out.update({group[1] + k: v for k, v in to_flat(value).items()})
    return out


def flat_keys(cls: type[DataclassInstance]) -> frozenset[str]:
    """Every flat key a record of *cls* reads and writes."""
    keys: set[str] = set()
    for f in fields(cls):
        group = _group_of(f.metadata)
        if group is None:
            keys.add(f.name)
        else:
            keys.update(group[1] + k for k in flat_keys(group[0]))
    return frozenset(keys)


def from_flat[T: DataclassInstance](cls: type[T], data: Mapping[str, Any]) -> T:
    """Build *cls* from a flat dict; unknown keys are ignored."""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        group = _group_of(f.metadata)
        if group is None:
            if f.name in data:
                kwargs[f.name] = data[f.name]
            continue
        inner, prefix = group
        sub = {k: data[prefix + k] for k in flat_keys(inner) if prefix + k in data}
        kwargs[f.name] = from_flat(inner, sub)
    return cls(**kwargs)
