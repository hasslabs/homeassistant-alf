"""Minimal Home Assistant stand-ins so the integration modules can be imported in tests.

Home Assistant itself is not a dev dependency (and needs a newer Python than the
recon venv), so this registers just enough of the `homeassistant.*` surface that
custom_components/alf touches. The stubs carry no behaviour of their own beyond
what the integration code reads (coordinator data / last_update_success, flow
result dicts); the logic under test is always the integration's.

Use `load_integration()`; it returns the integration package loaded under a private
name. Tests using it are skipped when a real Home Assistant is importable, so the
stubs never shadow the real thing.
"""
from __future__ import annotations

import enum
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Generic, TypeVar

_PKG = "alf_ha_under_test"
_INTEGRATION = Path(__file__).resolve().parent.parent / "custom_components" / "alf"

_T = TypeVar("_T")


def real_ha_available() -> bool:
    mod = sys.modules.get("homeassistant")
    if mod is not None:
        return not getattr(mod, "__alf_stub__", False)
    return importlib.util.find_spec("homeassistant") is not None


def _module(name: str, **attrs: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__alf_stub__ = True
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    parent, _, child = name.rpartition(".")
    if parent:
        mod_parent = sys.modules[parent]
        setattr(mod_parent, child, mod)
    return mod


# --- homeassistant.const / core / exceptions -------------------------------------------

class Platform(enum.StrEnum):
    BINARY_SENSOR = "binary_sensor"
    SENSOR = "sensor"
    SWITCH = "switch"


class UnitOfTemperature(enum.StrEnum):
    CELSIUS = "°C"


class UnitOfPower(enum.StrEnum):
    WATT = "W"


class UnitOfEnergy(enum.StrEnum):
    WATT_HOUR = "Wh"


class UnitOfElectricPotential(enum.StrEnum):
    VOLT = "V"


class HomeAssistant:  # only used as a type annotation
    pass


class ConfigEntryAuthFailed(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


# --- config entries / flows ------------------------------------------------------------

class ConfigEntry(Generic[_T]):
    def __init__(self, *, entry_id="entry-1", data=None, options=None, runtime_data=None):
        self.entry_id = entry_id
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.runtime_data = runtime_data
        self.update_listeners: list = []
        self.on_unload: list = []

    def add_update_listener(self, listener):
        self.update_listeners.append(listener)
        return ("remove-listener", listener)

    def async_on_unload(self, func):
        self.on_unload.append(func)


class _FlowBase:
    """Flow helpers return plain dicts describing the step result."""

    def async_show_progress(self, **kw):
        return {"type": "progress", **kw}

    def async_show_progress_done(self, *, next_step_id):
        return {"type": "progress_done", "step_id": next_step_id}

    def async_show_form(self, **kw):
        return {"type": "form", **kw}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_create_entry(self, **kw):
        return {"type": "create_entry", **kw}


class AbortFlow(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class ConfigFlow(_FlowBase):
    def __init_subclass__(cls, domain: str | None = None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.DOMAIN = domain

    source = "user"
    _configured_unique_ids: set = set()
    unique_id = None
    reauth_entry = None

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        if self.unique_id in self._configured_unique_ids:
            raise AbortFlow("already_configured")

    def async_remove(self):
        """HA's FlowHandler hook when a flow is abandoned; a no-op unless overridden."""

    def _get_reauth_entry(self):
        return self.reauth_entry

    def async_update_reload_and_abort(self, entry, *, data_updates):
        return {"type": "abort", "reason": "reauth_successful", "entry": entry,
                "data_updates": data_updates}


class OptionsFlow(_FlowBase):
    config_entry: ConfigEntry


# --- helpers ---------------------------------------------------------------------------

class EntityCategory(enum.StrEnum):
    DIAGNOSTIC = "diagnostic"


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator(Generic[_T]):
    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data: Any = None
        self.last_update_success = True
        self.refresh_requests = 0

    async def async_request_refresh(self):
        self.refresh_requests += 1

    async def async_config_entry_first_refresh(self):
        """Mirror HA: UpdateFailed -> ConfigEntryNotReady, auth failures propagate."""
        try:
            self.data = await self._async_update_data()
        except UpdateFailed as err:
            self.last_update_success = False
            raise ConfigEntryNotReady(str(err)) from err
        self.last_update_success = True


class CoordinatorEntity(Generic[_T]):
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


def _dr_async_get(hass):
    return hass.device_registry


def _dr_entries_for_config_entry(registry, entry_id):
    return registry.entries_for(entry_id)


def _sensor_classes():
    class SensorDeviceClass(enum.StrEnum):
        TEMPERATURE = "temperature"
        HUMIDITY = "humidity"
        POWER = "power"
        ENERGY = "energy"
        ILLUMINANCE = "illuminance"
        BATTERY = "battery"
        VOLTAGE = "voltage"

    class SensorStateClass(enum.StrEnum):
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"

    class SensorEntity:
        pass

    return SensorDeviceClass, SensorStateClass, SensorEntity


def _binary_classes():
    class BinarySensorDeviceClass(enum.StrEnum):
        SMOKE = "smoke"
        MOISTURE = "moisture"
        MOTION = "motion"
        OPENING = "opening"
        TAMPER = "tamper"
        PROBLEM = "problem"
        CONNECTIVITY = "connectivity"

    class BinarySensorEntity:
        pass

    return BinarySensorDeviceClass, BinarySensorEntity


class SwitchDeviceClass(enum.StrEnum):
    OUTLET = "outlet"


class SwitchEntity:
    pass


def _install_stubs() -> None:
    if "homeassistant" in sys.modules:
        return
    _module("homeassistant")
    _module(
        "homeassistant.const",
        Platform=Platform, LIGHT_LUX="lx", PERCENTAGE="%",
        UnitOfElectricPotential=UnitOfElectricPotential, UnitOfEnergy=UnitOfEnergy,
        UnitOfPower=UnitOfPower, UnitOfTemperature=UnitOfTemperature,
    )
    _module("homeassistant.core", HomeAssistant=HomeAssistant, callback=lambda f: f)
    _module("homeassistant.exceptions", ConfigEntryAuthFailed=ConfigEntryAuthFailed,
            ConfigEntryNotReady=ConfigEntryNotReady)
    _module(
        "homeassistant.config_entries",
        ConfigEntry=ConfigEntry, ConfigFlow=ConfigFlow, OptionsFlow=OptionsFlow,
        ConfigFlowResult=dict, SOURCE_REAUTH="reauth",
    )
    _module("homeassistant.helpers")
    _module(
        "homeassistant.helpers.device_registry",
        DeviceInfo=dict, DeviceEntry=object, async_get=_dr_async_get,
        async_entries_for_config_entry=_dr_entries_for_config_entry,
    )
    _module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator, CoordinatorEntity=CoordinatorEntity,
        UpdateFailed=UpdateFailed,
    )
    _module("homeassistant.helpers.entity", EntityCategory=EntityCategory)
    _module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _module("homeassistant.helpers.aiohttp_client",
            async_get_clientsession=lambda hass: hass.client_session)
    _module("homeassistant.components")
    sdc, ssc, se = _sensor_classes()
    _module("homeassistant.components.sensor",
            SensorDeviceClass=sdc, SensorStateClass=ssc, SensorEntity=se)
    bdc, be = _binary_classes()
    _module("homeassistant.components.binary_sensor",
            BinarySensorDeviceClass=bdc, BinarySensorEntity=be)
    _module("homeassistant.components.switch",
            SwitchDeviceClass=SwitchDeviceClass, SwitchEntity=SwitchEntity)
    if importlib.util.find_spec("voluptuous") is None:
        class Schema:
            def __init__(self, schema):
                self.schema = schema

        class Optional:
            def __init__(self, key, default=None):
                self.key = key
                self.default = default

            def __hash__(self):
                return hash(self.key)

            def __eq__(self, other):
                return self.key == getattr(other, "key", other)

        _module("voluptuous", Schema=Schema, Optional=Optional)


def load_integration() -> types.ModuleType:
    """Import custom_components/alf under a private package name, on top of the stubs."""
    if _PKG in sys.modules:
        return sys.modules[_PKG]
    _install_stubs()
    spec = importlib.util.spec_from_file_location(
        _PKG, _INTEGRATION / "__init__.py", submodule_search_locations=[str(_INTEGRATION)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[_PKG] = pkg
    spec.loader.exec_module(pkg)
    return pkg


def submodule(name: str) -> types.ModuleType:
    load_integration()
    return importlib.import_module(f"{_PKG}.{name}")
