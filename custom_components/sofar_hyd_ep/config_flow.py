"""Config + options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_FRAMING,
    CONF_KEEPALIVE,
    CONF_MAX_BATTERY_POWER,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    DEFAULT_KEEPALIVE,
    DEFAULT_MAX_BATTERY_POWER,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
)
from .modbus import FRAMING_RTU_OVER_TCP, FRAMING_TCP, ModbusError, SofarModbusClient
from .registers import decode

FRAMING_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[FRAMING_TCP, FRAMING_RTU_OVER_TCP],
        translation_key="framing",
        mode=SelectSelectorMode.LIST,
    )
)


async def _probe(data: dict) -> dict:
    client = SofarModbusClient(data[CONF_HOST], data[CONF_PORT], data[CONF_SLAVE], data[CONF_FRAMING])
    try:
        raw = {}
        words = await client.read_holding(0x0404, 1)  # SysState – proves the EP map answers
        raw[0x0404] = words[0]
        try:
            for i, w in enumerate(await client.read_holding(0x0445, 7)):
                raw[0x0445 + i] = w
        except ModbusError:
            pass
        return decode(raw)
    finally:
        await client.close()


class SofarConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if k != CONF_NAME}
            try:
                info = await _probe(data)
            except ModbusError:
                errors["base"] = "cannot_connect"
            else:
                serial = info.get("serial") or f"{data[CONF_HOST]}_{data[CONF_SLAVE]}"
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured(updates=data)
                title = user_input.get(CONF_NAME) or "Sofar HYD-EP"
                return self.async_create_entry(title=title, data=data)

        schema = vol.Schema({
            vol.Optional(CONF_NAME, default="Sofar HYD-EP"): str,
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(int, vol.Range(1, 65535)),
            vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): vol.All(int, vol.Range(1, 247)),
            vol.Required(CONF_FRAMING, default=FRAMING_TCP): FRAMING_SELECTOR,
        })
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _probe(user_input)
            except ModbusError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
            vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): vol.All(int, vol.Range(1, 65535)),
            vol.Required(CONF_SLAVE, default=entry.data[CONF_SLAVE]): vol.All(int, vol.Range(1, 247)),
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
                vol.All(int, vol.Range(3, 300)),
            vol.Required(CONF_MAX_BATTERY_POWER, default=o.get(CONF_MAX_BATTERY_POWER, DEFAULT_MAX_BATTERY_POWER)):
                vol.All(int, vol.Range(100, 20000)),
            vol.Required(CONF_KEEPALIVE, default=o.get(CONF_KEEPALIVE, DEFAULT_KEEPALIVE)): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
