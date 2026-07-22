"""Pure device-registry reconciliation logic - HA-free, loaded by file path.

Mirrors how the alfcloud layer is tested: no Home Assistant import, just fakes.
The helper decides *which* registry entries are orphaned; the coordinator glue that
actually calls the device registry is thin and covered by HA at runtime.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_CLEANUP = Path(__file__).resolve().parent.parent / "custom_components" / "alf" / "cleanup.py"
_spec = importlib.util.spec_from_file_location("alf_cleanup", _CLEANUP)
cleanup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cleanup)

orphaned_device_ids = cleanup.orphaned_device_ids

DOMAIN = "alf"


def _entry(reg_id: str, *identifiers: tuple[str, str]):
    """Fake device-registry entry: an id plus a set of (domain, key) identifiers."""
    return SimpleNamespace(id=reg_id, identifiers=set(identifiers))


def test_removed_and_readded_device_is_orphaned():
    # Old LeakBot "A" was removed & re-added in the Alf app, minting new id "B".
    # Only B comes back from the API; A's registry entry must be reported stale.
    entries = [
        _entry("reg-a", (DOMAIN, "A")),
        _entry("reg-b", (DOMAIN, "B")),
    ]
    assert orphaned_device_ids(entries, {"B"}, DOMAIN) == ["reg-a"]


def test_all_present_devices_are_kept():
    entries = [_entry("reg-a", (DOMAIN, "A")), _entry("reg-b", (DOMAIN, "B"))]
    assert orphaned_device_ids(entries, {"A", "B"}, DOMAIN) == []


def test_empty_inventory_removes_nothing():
    # An empty fetch is ambiguous (truly empty account vs. a transient blank response).
    # Never mass-remove on it; manual deletion covers the genuine last-device case.
    entries = [_entry("reg-a", (DOMAIN, "A")), _entry("reg-b", (DOMAIN, "B"))]
    assert orphaned_device_ids(entries, set(), DOMAIN) == []


def test_foreign_identifiers_are_left_alone():
    # An entry carrying no alf identifier is never our business to remove.
    entries = [_entry("reg-x", ("othervendor", "X"))]
    assert orphaned_device_ids(entries, {"A"}, DOMAIN) == []


def test_entry_kept_when_any_alf_identifier_is_live():
    entries = [_entry("reg-ab", (DOMAIN, "A"), (DOMAIN, "B"))]
    assert orphaned_device_ids(entries, {"B"}, DOMAIN) == []


def test_multiple_stale_entries_all_reported():
    entries = [
        _entry("reg-a", (DOMAIN, "A")),
        _entry("reg-b", (DOMAIN, "B")),
        _entry("reg-c", (DOMAIN, "C")),
    ]
    assert sorted(orphaned_device_ids(entries, {"B"}, DOMAIN)) == ["reg-a", "reg-c"]
