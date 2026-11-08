"""Buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import SofarEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SyncClockButton(entry.runtime_data)])


class SyncClockButton(SofarEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sync_clock")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        await self.coordinator.async_sync_time()
