"""Buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import SofarEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = [RedetectButton(c)]
    if c.has("clock_year"):
        entities.append(SyncClockButton(c))
    if c.hybrid:
        entities.append(ClearSlotsButton(c))
    if c.hybrid and c.modern:
        entities += [ApplyNativeButton(c, "timing"), ApplyNativeButton(c, "tou")]
    async_add_entities(entities)


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


class ApplyNativeButton(SofarEntity, ButtonEntity):
    """Write slot 1 / rule 1 to the inverter and switch it to that mode."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-sync"

    def __init__(self, coordinator, kind: str) -> None:
        super().__init__(coordinator, f"apply_{kind}")
        self._kind = kind

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        await self.coordinator.async_apply_native_slot1(self._kind)


class ClearSlotsButton(SofarEntity, ButtonEntity):
    _attr_icon = "mdi:calendar-remove"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "clear_slots")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        await self.coordinator.async_clear_slots()


class RedetectButton(SofarEntity, ButtonEntity):
    """Run autodetection again (after a firmware update or adding a battery)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:magnify-scan"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "redetect")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        await self.coordinator.async_redetect()
