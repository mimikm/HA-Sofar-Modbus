"""Sofar HYD-EP inverter over a Modbus IP gateway."""
from __future__ import annotations

from datetime import datetime
import json
import logging

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import CONF_FRAMING, CONF_SLAVE, DOMAIN, PLATFORMS
from .coordinator import SofarCoordinator
from .modbus import SofarModbusClient
from .registers import BATTERY_ACTIONS, SCAN_RANGES

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SofarConfigEntry = ConfigEntry[SofarCoordinator]

ENTRY = vol.Optional("config_entry_id")
POWER = vol.All(vol.Coerce(int), vol.Range(-50000, 50000))


async def async_setup(hass: HomeAssistant, config) -> bool:
    def _coordinator(call: ServiceCall) -> SofarCoordinator:
        entry_id = call.data.get("config_entry_id")
        entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED and (entry_id is None or e.entry_id == entry_id)
        ]
        if not entries:
            raise ServiceValidationError("No loaded Sofar HYD-EP inverter found")
        return entries[0].runtime_data

    async def set_passive(call: ServiceCall) -> None:
        await _coordinator(call).async_set_passive(
            call.data["grid_power"], call.data["battery_min"], call.data["battery_max"]
        )

    async def battery_action(call: ServiceCall) -> None:
        await _coordinator(call).async_battery_action(call.data["action"], call.data.get("power"))

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

    hass.services.async_register(
        DOMAIN, "set_passive", set_passive,
        schema=vol.Schema({ENTRY: str, vol.Required("grid_power"): POWER,
                           vol.Required("battery_min"): POWER, vol.Required("battery_max"): POWER}),
    )
    hass.services.async_register(
        DOMAIN, "battery_action", battery_action,
        schema=vol.Schema({ENTRY: str, vol.Required("action"): vol.In(BATTERY_ACTIONS),
                           vol.Optional("power"): vol.All(vol.Coerce(int), vol.Range(0, 50000))}),
    )
    hass.services.async_register(
        DOMAIN, "scan_registers", scan_registers,
        schema=vol.Schema({ENTRY: str, vol.Optional("start"): vol.Coerce(int),
                           vol.Optional("count"): vol.All(vol.Coerce(int), vol.Range(1, 2048))}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SofarConfigEntry) -> bool:
    client = SofarModbusClient(
        entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_SLAVE], entry.data[CONF_FRAMING]
    )
    coordinator = SofarCoordinator(hass, entry, client)
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
