"""Sofar inverters over Modbus (IP gateway)."""
from __future__ import annotations

from datetime import datetime
import json
import logging

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store

from .const import CONF_FRAMING, CONF_SLAVE, DOMAIN, PLATFORMS
from .coordinator import SofarCoordinator
from .detect import UnsupportedInverter, detect
from .modbus import ModbusError, SofarModbusClient
from .registers import BATTERY_ACTIONS, SCAN_RANGES, WEEKDAYS, normalise_action

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SofarConfigEntry = ConfigEntry[SofarCoordinator]

ENTRY = vol.Optional("config_entry_id")
DEVICE = vol.Optional("device_id")
POWER = vol.All(vol.Coerce(int), vol.Range(-50000, 50000))
POS_POWER = vol.All(vol.Coerce(int), vol.Range(0, 50000))
WHEN = vol.Any(cv.time, cv.datetime)
SOC = vol.All(vol.Coerce(int), vol.Range(0, 100))
SLOT_NO = vol.All(vol.Coerce(int), vol.Range(1, 4))


async def async_setup(hass: HomeAssistant, config) -> bool:
    def _coordinator(call: ServiceCall) -> SofarCoordinator:
        entry_id = call.data.get("config_entry_id")
        if entry_id is None and call.data.get("device_id"):
            dev_ids = call.data["device_id"]
            dev_ids = dev_ids if isinstance(dev_ids, list) else [dev_ids]
            registry = dr.async_get(hass)
            for dev_id in dev_ids:
                device = registry.async_get(dev_id)
                if device is None:
                    continue
                for eid in device.config_entries:
                    entry = hass.config_entries.async_get_entry(eid)
                    if entry and entry.domain == DOMAIN:
                        entry_id = eid
            if entry_id is None:
                raise ServiceValidationError("device_id is not a Sofar Modbus device")
        entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED and (entry_id is None or e.entry_id == entry_id)
        ]
        if not entries:
            raise ServiceValidationError("No loaded Sofar inverter found")
        return entries[0].runtime_data

    async def set_passive(call: ServiceCall) -> None:
        await _coordinator(call).async_set_passive(
            call.data["grid_power"], call.data["battery_min"], call.data["battery_max"]
        )

    async def battery_action(call: ServiceCall) -> None:
        raw = next((call.data[k] for k in ("action", "operation", "mode") if call.data.get(k)), None)
        action = normalise_action(raw)
        if action is None:
            raise ServiceValidationError(
                f"Unknown battery action {raw!r}. Use one of: {', '.join(BATTERY_ACTIONS)} "
                "(or auto, charge, discharge, pause, freeze_charge, freeze_discharge)")
        def _num(key):
            value = call.data.get(key)
            return None if value in (None, "") else int(value)

        target = _num("target_soc")
        await _coordinator(call).async_battery_action(
            action, _num("power"), target if target else None)

    async def scan_registers(call: ServiceCall):
        coord = _coordinator(call)
        ranges = SCAN_RANGES
        if "start" in call.data:
            start = int(call.data["start"])
            ranges = [(start, start + int(call.data.get("count", 64)) - 1)]
        result = await coord.async_scan(ranges)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = hass.config.path(f"sofar_register_scan_{stamp}.txt")

        def _write() -> None:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("address  hex     unsigned  signed\n")
                for addr, val in result.items():
                    if isinstance(val, int):
                        signed = val - 0x10000 if val & 0x8000 else val
                        fh.write(f"{addr}   0x{val:04X}  {val:8d}  {signed:6d}\n")
                    else:
                        fh.write(f"{addr}   {val}\n")
                fh.write("\n" + json.dumps(result))

        await hass.async_add_executor_job(_write)
        readable = sum(1 for v in result.values() if isinstance(v, int))
        persistent_notification.async_create(
            hass,
            f"Read {readable} of {len(result)} registers. Saved to `{path}`.",
            title="Sofar register scan",
        )
        return {"file": path, "registers": result}

    async def add_slot(call: ServiceCall):
        action = "charge" if call.service == "charge_slot" else "discharge"
        slot = await _coordinator(call).async_add_slot(
            action, call.data["start"], call.data["end"], call.data.get("power"),
            call.data.get("soc"), call.data.get("daily", False))
        return {"slot": slot}

    async def clear_slots(call: ServiceCall) -> None:
        await _coordinator(call).async_clear_slots(call.data.get("slot_id"))

    async def set_timing_slot(call: ServiceCall) -> None:
        d = call.data
        await _coordinator(call).async_apply_timing(
            d["slot"], charge_enabled=d["charge_enabled"], discharge_enabled=d["discharge_enabled"],
            charge_start=d["charge_start"], charge_end=d["charge_end"],
            discharge_start=d["discharge_start"], discharge_end=d["discharge_end"],
            charge_power=d["charge_power"], discharge_power=d["discharge_power"],
            activate=d["activate"])

    async def set_tou_rule(call: ServiceCall) -> None:
        d = call.data
        await _coordinator(call).async_apply_tou(
            d["rule"], enabled=d["enabled"], start=d["start"], end=d["end"],
            target_soc=d["target_soc"], power=d["power"], weekdays=d.get("weekdays"),
            activate=d["activate"])

    slot_schema = vol.Schema({ENTRY: str, DEVICE: vol.Any(str, [str]), vol.Required("start"): WHEN, vol.Required("end"): WHEN,
                              vol.Optional("power"): POS_POWER, vol.Optional("soc"): SOC,
                              vol.Optional("daily", default=False): cv.boolean})
    for name in ("charge_slot", "discharge_slot"):
        hass.services.async_register(DOMAIN, name, add_slot, schema=slot_schema,
                                     supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "clear_slots", clear_slots,
                                 schema=vol.Schema({ENTRY: str, DEVICE: vol.Any(str, [str]), vol.Optional("slot_id"): str}))
    hass.services.async_register(
        DOMAIN, "set_timing_slot", set_timing_slot,
        schema=vol.Schema({
            ENTRY: str, vol.Required("slot"): SLOT_NO,
            vol.Optional("charge_enabled", default=True): cv.boolean,
            vol.Optional("charge_start", default="00:00"): cv.time,
            vol.Optional("charge_end", default="00:00"): cv.time,
            vol.Optional("charge_power", default=0): POS_POWER,
            vol.Optional("discharge_enabled", default=False): cv.boolean,
            vol.Optional("discharge_start", default="00:00"): cv.time,
            vol.Optional("discharge_end", default="00:00"): cv.time,
            vol.Optional("discharge_power", default=0): POS_POWER,
            vol.Optional("activate", default=True): cv.boolean,
        }))
    hass.services.async_register(
        DOMAIN, "set_tou_rule", set_tou_rule,
        schema=vol.Schema({
            ENTRY: str, vol.Required("rule"): SLOT_NO,
            vol.Optional("enabled", default=True): cv.boolean,
            vol.Required("start"): cv.time, vol.Required("end"): cv.time,
            vol.Optional("target_soc", default=100): vol.All(vol.Coerce(int), vol.Range(30, 100)),
            vol.Required("power"): POS_POWER,
            vol.Optional("weekdays"): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
            vol.Optional("activate", default=True): cv.boolean,
        }))
    hass.services.async_register(
        DOMAIN, "set_passive", set_passive,
        schema=vol.Schema({ENTRY: str, DEVICE: vol.Any(str, [str]), vol.Required("grid_power"): POWER,
                           vol.Required("battery_min"): POWER, vol.Required("battery_max"): POWER}),
    )
    hass.services.async_register(
        DOMAIN, "battery_action", battery_action,
        # Lenient on purpose: Predbat and older templates may send "operation" instead of
        # "action", strings for numbers, or extra keys it adds itself.
        schema=vol.Schema({ENTRY: str, DEVICE: vol.Any(str, [str]),
                           vol.Optional("action"): cv.string, vol.Optional("operation"): cv.string,
                           vol.Optional("mode"): cv.string,
                           vol.Optional("power"): vol.Any(None, "", vol.All(vol.Coerce(float), vol.Coerce(int),
                                                                         vol.Range(0, 50000))),
                           vol.Optional("target_soc"): vol.Any(None, "", vol.All(vol.Coerce(float), vol.Coerce(int),
                                                                              vol.Range(0, 100)))},
                          extra=vol.ALLOW_EXTRA),
    )
    hass.services.async_register(
        DOMAIN, "scan_registers", scan_registers,
        schema=vol.Schema({ENTRY: str, DEVICE: vol.Any(str, [str]), vol.Optional("start"): vol.Coerce(int),
                           vol.Optional("count"): vol.All(vol.Coerce(int), vol.Range(1, 2048))}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SofarConfigEntry) -> bool:
    client = SofarModbusClient(
        entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_SLAVE], entry.data[CONF_FRAMING]
    )
    if not entry.data.get("profile"):
        # First start (or upgrade from v0.2): detect what this inverter has.
        try:
            profile = await detect(client)
        except UnsupportedInverter as err:
            await client.close()
            raise ConfigEntryError(
                "This Sofar uses the older ME3000/HYD-ES protocol, which isn't supported yet"
            ) from err
        except ModbusError as err:
            await client.close()
            raise ConfigEntryNotReady(f"Inverter not reachable: {err}") from err
        hass.config_entries.async_update_entry(entry, data={**entry.data, "profile": profile})

    coordinator = SofarCoordinator(hass, entry, client)
    coordinator.slot_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.slots")
    stored = await coordinator.slot_store.async_load()
    if stored:
        coordinator.slots = stored.get("slots", [])
        coordinator.goal = stored.get("goal")
        if stored.get("applied"):
            # A slot was driving the battery when HA stopped: re-apply or hand back to Auto.
            coordinator._slot_applied = ("restored", -1)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.close()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    return True


async def _reload_on_options(hass: HomeAssistant, entry: SofarConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SofarConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.client.close()
    return ok
