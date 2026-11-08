"""Time entities for the native Timing slot 1 / Time of use rule 1 (written on Apply)."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import SofarEntity

KEYS = ["timing_charge_start", "timing_charge_end", "timing_discharge_start",
        "timing_discharge_end", "tou_start", "tou_end"]


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.hybrid:
        async_add_entities(NativeTime(entry.runtime_data, k) for k in KEYS)


class NativeTime(SofarEntity, TimeEntity, RestoreEntity):
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable"):
            self.coordinator.native[self._key] = last.state[:5]

    @property
    def native_value(self) -> time:
        h, m = (int(x) for x in self.coordinator.native[self._key].split(":")[:2])
        return time(h, m)

    async def async_set_value(self, value: time) -> None:
        self.coordinator.native[self._key] = value.strftime("%H:%M")
        self.async_write_ha_state()
