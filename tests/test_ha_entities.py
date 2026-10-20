"""Which entities the platforms create from a device's features, and what they report.

The platform modules are loaded on top of tests/ha_stubs.py (no Home Assistant
install). The mapping rules under test are the integration's own: bools become
binary sensors, numbers with a known kind become typed sensors, anything else
becomes a diagnostic entity, LeakBot bits get their special handling, and plug
switches only appear when control is enabled.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests import ha_stubs

pytestmark = pytest.mark.skipif(
    ha_stubs.real_ha_available(), reason="real Home Assistant installed; stubs not used"
)

if not ha_stubs.real_ha_available():
    alf = ha_stubs.load_integration()
    binary_sensor = ha_stubs.submodule("binary_sensor")
    sensor = ha_stubs.submodule("sensor")
    switch = ha_stubs.submodule("switch")
    entity_mod = ha_stubs.submodule("entity")
    coordinator_mod = ha_stubs.submodule("coordinator")
    models = ha_stubs.submodule("alfcloud.models")


def _feature(fid, value, dfid=None):
    return {"id": fid, "deviceFeatureId": dfid or f"df-{fid}", "current": {"value": value}}


def _device(did="dev-1", *, state="online", features=(), battery_pct=None, battery_v=None,
            parent=None, room=None, home="home-1"):
    status = {}
    if battery_pct is not None:
        status["percentage"] = {"value": battery_pct}
    if battery_v is not None:
        status["voltage"] = {"value": battery_v}
    return models.Device.from_json({
        "id": did, "name": f"Device {did}", "type": "x", "state": state, "homeId": home,
        "roomId": room, "parentId": parent,
        "specifications": {"vendor": "frient", "modelName": "Model", "serialNumber": "SN",
                           "firmwareVersion": "1.0"},
        "power": {"status": status},
        "features": list(features),
    })


def _coordinator(*devices, homes=None):
    entry = ha_stubs.ConfigEntry(data={"refresh_token": "rt"})
    coord = coordinator_mod.AlfDataUpdateCoordinator(
        SimpleNamespace(), entry, client=SimpleNamespace(), auth=SimpleNamespace()
    )
    coord.data = {d.id: d for d in devices}
    coord.homes = homes or {}
    return coord


async def _setup(platform, coord, options=None):
    entry = ha_stubs.ConfigEntry(options=options, runtime_data=coord)
    added = []
    await platform.async_setup_entry(None, entry, lambda ents: added.extend(ents))
    return added


def _by_uid(entities):
    return {e._attr_unique_id: e for e in entities}


# --- humanize_feature ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fid", "expected"),
    [
        ("leakbot.highFlow", "High flow"),
        ("generic.temperature", "Temperature"),
        ("x.someLongCamelName", "Some long camel name"),
        ("noDots", "No dots"),
        ("a.b.lastPart", "Last part"),
    ],
)
def test_humanize_feature(fid, expected):
    assert entity_mod.humanize_feature(fid) == expected


# --- binary sensors --------------------------------------------------------------------

async def test_binary_platform_maps_bools_and_adds_connectivity():
    dev = _device(features=[
        _feature("fire.smoke", False),
        _feature("leakbot.leak", True),
        _feature("generic.temperature", 21.5),  # not a bool -> not a binary sensor
        _feature("weird.mysteryFlag", True),
    ])
    ents = _by_uid(await _setup(binary_sensor, _coordinator(dev)))

    assert set(ents) == {
        "dev-1:connectivity", "dev-1:fire.smoke", "dev-1:leakbot.leak", "dev-1:weird.mysteryFlag",
    }
    smoke = ents["dev-1:fire.smoke"]
    assert smoke._attr_device_class == "smoke"
    assert smoke._attr_translation_key == "smoke"
    assert smoke.is_on is False
    leak = ents["dev-1:leakbot.leak"]
    assert leak._attr_device_class == "moisture"
    assert leak.is_on is True
    unknown = ents["dev-1:weird.mysteryFlag"]
    assert unknown._attr_entity_category == "diagnostic"
    assert unknown._attr_name == "Mystery flag"
    assert not hasattr(unknown, "_attr_device_class")


async def test_leakbot_diagnostic_bits_are_named_not_alarms_and_onpipe_disabled():
    dev = _device(features=[
        _feature("leakbot.highFlow", False),
        _feature("leakbot.hotPipe", True),
        _feature("leakbot.onPipe", True),
    ])
    ents = _by_uid(await _setup(binary_sensor, _coordinator(dev)))

    for fid, key in [("leakbot.highFlow", "high_flow"), ("leakbot.hotPipe", "hot_pipe"),
                     ("leakbot.onPipe", "on_pipe")]:
        ent = ents[f"dev-1:{fid}"]
        assert ent._attr_translation_key == key
        assert ent._attr_entity_category == "diagnostic"
        assert not hasattr(ent, "_attr_device_class")  # never PROBLEM - no crying wolf
    assert ents["dev-1:leakbot.onPipe"]._attr_entity_registry_enabled_default is False
    assert not hasattr(ents["dev-1:leakbot.hotPipe"], "_attr_entity_registry_enabled_default")


async def test_connectivity_stays_available_while_device_offline():
    dev = _device(state="offline", features=[_feature("fire.smoke", False)])
    coord = _coordinator(dev)
    ents = _by_uid(await _setup(binary_sensor, coord))

    conn = ents["dev-1:connectivity"]
    assert conn.available is True
    assert conn.is_on is False
    assert ents["dev-1:fire.smoke"].available is False  # regular entities go unavailable

    coord.last_update_success = False
    assert conn.available is False


async def test_entities_handle_device_vanishing_from_coordinator():
    dev = _device(features=[_feature("fire.smoke", True)])
    coord = _coordinator(dev)
    ents = _by_uid(await _setup(binary_sensor, coord))
    coord.data = {}

    assert ents["dev-1:fire.smoke"].is_on is None
    assert ents["dev-1:fire.smoke"].available is False
    assert ents["dev-1:connectivity"].is_on is None
    assert ents["dev-1:connectivity"].available is False


# --- sensors ---------------------------------------------------------------------------

async def test_sensor_platform_types_known_kinds_and_diagnoses_the_rest():
    dev = _device(features=[
        _feature("generic.temperature", 21.5),
        _feature("generic.humidity", 40),
        _feature("smartplug.demand", 12.0),
        _feature("smartplug.summationDelivered", 1234),
        _feature("generic.illuminance", 300),
        _feature("generic.firmwareMode", "normal"),   # string -> diagnostic
        _feature("generic.temperatureText", "warm"),  # known kind but not numeric -> diagnostic
        _feature("fire.smoke", True),                 # bool -> skipped here
        _feature("generic.nothing", None),            # None -> skipped
        _feature("generic.listy", [1, 2]),            # unsupported type -> skipped
    ])
    ents = _by_uid(await _setup(sensor, _coordinator(dev)))

    assert set(ents) == {
        "dev-1:generic.temperature", "dev-1:generic.humidity", "dev-1:smartplug.demand",
        "dev-1:smartplug.summationDelivered", "dev-1:generic.illuminance",
        "dev-1:generic.firmwareMode", "dev-1:generic.temperatureText",
    }
    temp = ents["dev-1:generic.temperature"]
    assert (temp._attr_device_class, temp._attr_native_unit_of_measurement,
            temp._attr_state_class) == ("temperature", "°C", "measurement")
    assert temp.native_value == 21.5
    energy = ents["dev-1:smartplug.summationDelivered"]
    assert energy._attr_device_class == "energy"
    assert energy._attr_native_unit_of_measurement == "Wh"
    assert energy._attr_state_class == "total_increasing"
    power = ents["dev-1:smartplug.demand"]
    assert (power._attr_device_class, power._attr_native_unit_of_measurement) == ("power", "W")
    assert ents["dev-1:generic.illuminance"]._attr_native_unit_of_measurement == "lx"
    diag = ents["dev-1:generic.firmwareMode"]
    assert diag._attr_entity_category == "diagnostic"
    assert diag._attr_name == "Firmware mode"
    assert diag.native_value == "normal"
    assert isinstance(ents["dev-1:generic.temperatureText"], sensor.AlfDiagnosticSensor)


async def test_battery_percentage_preferred_over_voltage():
    pct = _device("pct", battery_pct=87, battery_v=3.0)
    volt = _device("volt", battery_v=2.9)
    none = _device("mains")
    ents = _by_uid(await _setup(sensor, _coordinator(pct, volt, none)))

    assert set(ents) == {"pct:battery", "volt:battery"}
    assert ents["pct:battery"]._attr_device_class == "battery"
    assert ents["pct:battery"]._attr_native_unit_of_measurement == "%"
    assert ents["pct:battery"].native_value == 87
    assert ents["volt:battery"]._attr_device_class == "voltage"
    assert ents["volt:battery"]._attr_translation_key == "battery_voltage"
    assert ents["volt:battery"].native_value == 2.9


async def test_sensor_values_none_when_device_gone():
    dev = _device(battery_pct=50, features=[_feature("generic.temperature", 20),
                                            _feature("generic.mode", "x")])
    coord = _coordinator(dev)
    ents = await _setup(sensor, coord)
    coord.data = {}
    assert [e.native_value for e in ents] == [None, None, None]


# --- device info -----------------------------------------------------------------------

async def test_device_info_links_gateway_and_suggests_room_area():
    home = models.Home.from_json({"id": "home-1", "name": "Hem",
                                  "rooms": [{"id": "r1", "name": "Kitchen"}]})
    child = _device("child", parent="gw", room="r1", features=[_feature("fire.smoke", False)])
    gateway = _device("gw")
    ents = _by_uid(await _setup(binary_sensor, _coordinator(child, gateway,
                                                            homes={"home-1": home})))

    info = ents["child:fire.smoke"].device_info
    assert info["identifiers"] == {("alf", "child")}
    assert info["via_device"] == ("alf", "gw")
    assert info["suggested_area"] == "Kitchen"
    assert info["manufacturer"] == "frient"
    assert info["serial_number"] == "SN"
    gw_info = ents["gw:connectivity"].device_info
    assert "via_device" not in gw_info
    assert "suggested_area" not in gw_info


async def test_device_info_falls_back_to_id_when_device_gone():
    coord = _coordinator(_device("d"))
    ents = await _setup(binary_sensor, coord)
    coord.data = {}
    info = ents[0].device_info
    assert info["name"] == "d"
    assert info["manufacturer"] is None
    assert "suggested_area" not in info


# --- switches --------------------------------------------------------------------------

async def test_no_switches_unless_control_enabled():
    dev = _device(features=[_feature("smartplug.onOff", True)])
    assert await _setup(switch, _coordinator(dev)) == []
    assert await _setup(switch, _coordinator(dev), {"enable_control": False}) == []


async def test_switch_created_only_for_plugs_and_sends_feature_writes():
    plug = _device("plug", features=[_feature("smartplug.onOff", False, dfid="df-plug")])
    other = _device("smoke", features=[_feature("fire.smoke", False)])
    coord = _coordinator(plug, other)
    calls = []

    async def set_feature(home_id, device_feature_id, value):
        calls.append((home_id, device_feature_id, value))

    coord.client = SimpleNamespace(async_set_feature=set_feature)
    ents = await _setup(switch, coord, {"enable_control": True})

    assert [e._attr_unique_id for e in ents] == ["plug:smartplug.onOff"]
    sw = ents[0]
    assert sw.is_on is False
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert calls == [("home-1", "df-plug", True), ("home-1", "df-plug", False)]
    assert coord.refresh_requests == 2


async def test_switch_write_is_skipped_when_device_gone():
    plug = _device("plug", features=[_feature("smartplug.onOff", True)])
    coord = _coordinator(plug)
    coord.client = SimpleNamespace(async_set_feature=None)  # would crash if called
    sw = (await _setup(switch, coord, {"enable_control": True}))[0]
    coord.data = {}

    await sw.async_turn_on()
    assert sw.is_on is None
    assert coord.refresh_requests == 0


# --- __init__.async_remove_config_entry_device -----------------------------------------

@pytest.mark.parametrize(
    ("identifiers", "allowed"),
    [
        ({("alf", "live")}, False),       # still reported upstream -> refuse
        ({("alf", "gone")}, True),        # stale -> allow deletion
        ({("other", "live")}, True),      # not ours by domain
        ({("alf", "gone"), ("alf", "live")}, False),
    ],
)
async def test_remove_device_only_allowed_when_not_live(identifiers, allowed):
    entry = ha_stubs.ConfigEntry(runtime_data=_coordinator(_device("live")))
    device_entry = SimpleNamespace(identifiers=identifiers)
    assert await alf.async_remove_config_entry_device(None, entry, device_entry) is allowed
