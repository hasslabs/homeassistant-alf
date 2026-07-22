"""Pure logic for reconciling the HA device registry against live Alf devices.

Deliberately import-free (no Home Assistant, no .const) so it stays unit-testable
without the HA test harness, matching how the alfcloud layer is tested.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def orphaned_device_ids(
    entries: Iterable[Any], live_ids: set[str], domain: str
) -> list[str]:
    """Return the registry ids of device entries whose Alf device is gone upstream.

    ``entries`` are device-registry entries (each with ``.id`` and ``.identifiers``,
    a set of ``(domain, key)`` tuples) that belong to this config entry. ``live_ids``
    is the set of Alf device ids the latest successful poll returned.

    An entry is an orphan when it carries at least one ``domain`` identifier and none
    of those keys are live. A device only vanishes from the Alf API when genuinely
    removed from the account (offline devices are still returned), so this reliably
    catches the remove-and-re-add case, which mints a fresh device id.

    Returns an empty list when ``live_ids`` is empty: a blank inventory is ambiguous
    (truly empty account vs. a transient empty response), so we never mass-remove on
    it - manual deletion covers the genuine "removed my last device" case instead.
    """
    if not live_ids:
        return []
    orphaned: list[str] = []
    for entry in entries:
        keys = {key for dom, key in entry.identifiers if dom == domain}
        if keys and keys.isdisjoint(live_ids):
            orphaned.append(entry.id)
    return orphaned
