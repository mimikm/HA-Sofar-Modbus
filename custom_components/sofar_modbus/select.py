"""Selects: energy storage mode, battery action, passive timeout action."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .entity import SofarEntity
from .registers import BATTERY_ACTIONS, STORAGE_MODES, TIMEOUT_ACTIONS


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    if c.hybrid:
        async_add_entities([StorageModeSelect(c), BatteryActionSelect(c), TimeoutActionSelect(c)])


class StorageModeSelect(SofarEntity, SelectEntity):
    _attr_options = list(STORAGE_MODES.values())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "energy_storage_mode")

    @property
    def current_option(self):
        return (self.coordinator.data or {}).get("energy_storage_mode_text")

    async def async_select_option(self, option: str) -> None:
        mode = next(k for k, v in STORAGE_MODES.items() if v == option)
        await self.coordinator.async_set_storage_mode(mode)


class BatteryActionSelect(SofarEntity, SelectEntity):
    """One-tap battery control built on passive mode (power from the 'Battery action power' number)."""

    _attr_icon = "mdi:battery-sync"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "battery_action")
        self._attr_unique_id += "_select"
        self._attr_translation_key = "battery_action_select"

    @property
    def options(self) -> list[str]:
        cur = self.current_option
        return BATTERY_ACTIONS + ([cur] if cur and cur not in BATTERY_ACTIONS else [])

    @property
    def current_option(self):
        return (self.coordinator.data or {}).get("battery_action")

    async def async_select_option(self, option: str) -> None:
        if option in BATTERY_ACTIONS:
            await self.coordinator.async_battery_action(option)


class TimeoutActionSelect(SofarEntity, SelectEntity):
    _attr_options = list(TIMEOUT_ACTIONS.values())
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "passive_timeout_action")

    @property
    def current_option(self):
        return (self.coordinator.data or {}).get("passive_timeout_action_text")

    async def async_select_option(self, option: str) -> None:
        action = next(k for k, v in TIMEOUT_ACTIONS.items() if v == option)
        await self.coordinator.async_set_passive_timeout(action=action)
