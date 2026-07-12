import json
import pathlib

from alfcloud.models import parse_devices, parse_homes

FIX = pathlib.Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_parse_devices_basic():
    devices = parse_devices(_load("devices_sample.json"))
    by_id = {d.id: d for d in devices}
    assert set(by_id) == {"dev-gw", "dev-plug", "dev-smoke"}
    plug = by_id["dev-plug"]
    assert plug.type == "frient.smartplug"
    assert plug.online is True
    assert plug.parent_id == "dev-gw"
    assert plug.model_name == "Frient Smart Plug Mini"
    assert plug.value("smartplug.onOff") is True
    assert plug.value("smartplug.summationDelivered") == 11227
    assert plug.value("does.not.exist") is None


def test_parse_devices_battery_and_temperature():
    devices = parse_devices(_load("devices_sample.json"))
    smoke = next(d for d in devices if d.id == "dev-smoke")
    assert smoke.power_source == "battery"
    assert smoke.battery_voltage == 3
    assert smoke.battery_percentage is None
    assert smoke.value("smokeDetector.fire") is False
    assert smoke.value("generic.temperature") == 26.6


def test_parse_homes_and_room_lookup():
    homes = parse_homes(_load("homes_sample.json"))
    assert len(homes) == 1
    home = homes[0]
    assert home.id == "home-0001"
    assert home.name == "Hemma"
    assert home.room_name("room-sov") == "Sovrum"
    assert home.room_name(None) is None
    assert home.room_name("unknown-room") is None


def test_parse_devices_handles_empty_payload():
    assert parse_devices({}) == []
    assert parse_devices({"devices": []}) == []
