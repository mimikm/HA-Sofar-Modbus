"""Config + options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_AUTO_TIME_SYNC,
    CONF_FRAMING,
    CONF_KEEPALIVE,
    CONF_MAX_BATTERY_POWER,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    DEFAULT_AUTO_TIME_SYNC,
    DEFAULT_KEEPALIVE,
    DEFAULT_MAX_BATTERY_POWER,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
)
from .modbus import FRAMING_RTU_OVER_TCP, FRAMING_TCP, ModbusError, SofarModbusClient
from .detect import UnsupportedInverter, detect

def _box(lo: int, hi: int, unit: str | None = None):
    return vol.All(
        NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=1, mode=NumberSelectorMode.BOX,
                                            unit_of_measurement=unit)),
        vol.Coerce(int),
    )


FRAMING_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[FRAMING_TCP, FRAMING_RTU_OVER_TCP],
        translation_key="framing",
        mode=SelectSelectorMode.LIST,
    )
)


async def _detect(data: dict) -> dict:
    client = SofarModbusClient(data[CONF_HOST], data[CONF_PORT], data[CONF_SLAVE], data[CONF_FRAMING])
    try:
        return await detect(client)
    finally:
        await client.close()


class SofarConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}
        self._title = "Sofar"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if k != CONF_NAME}
            try:
                profile = await _detect(data)
            except UnsupportedInverter:
                errors["base"] = "legacy_unsupported"
            except ModbusError:
                errors["base"] = "cannot_connect"
            else:
                serial = profile.get("serial") or f"{data[CONF_HOST]}_{data[CONF_SLAVE]}"
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured(updates=data)
                self._data = {**data, "profile": profile}
                self._title = user_input.get(CONF_NAME) or "Sofar"
                return await self.async_step_confirm()

        schema = vol.Schema({
            vol.Optional(CONF_NAME, default="Sofar"): str,
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): _box(1, 65535),
            vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): _box(1, 247),
            vol.Required(CONF_FRAMING, default=FRAMING_TCP): FRAMING_SELECTOR,
        })
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=self._title, data=self._data)
        p = self._data["profile"]
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "model": p["model"],
                "serial": p.get("serial") or "unknown",
                "firmware": p.get("sw_version") or "unknown",
                "registers": str(len(p["registers"])),
            },
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                profile = await _detect(user_input)
            except UnsupportedInverter:
                errors["base"] = "legacy_unsupported"
            except ModbusError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={**user_input, "profile": profile})
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
            vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): _box(1, 65535),
            vol.Required(CONF_SLAVE, default=entry.data[CONF_SLAVE]): _box(1, 247),
            vol.Required(CONF_FRAMING, default=entry.data[CONF_FRAMING]): FRAMING_SELECTOR,
        })
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return SofarOptionsFlow()


class SofarOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                _box(3, 300, "s"),
            vol.Required(CONF_MAX_BATTERY_POWER, default=o.get(CONF_MAX_BATTERY_POWER, DEFAULT_MAX_BATTERY_POWER)):
                _box(100, 20000, "W"),
            vol.Required(CONF_KEEPALIVE, default=o.get(CONF_KEEPALIVE, DEFAULT_KEEPALIVE)): bool,
            vol.Required(CONF_AUTO_TIME_SYNC, default=o.get(CONF_AUTO_TIME_SYNC, DEFAULT_AUTO_TIME_SYNC)): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
