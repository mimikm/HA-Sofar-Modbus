"""Remote on/off switch (disabled by default – it really turns the inverter off)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .entity import SofarEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RemoteOnOff(entry.runtime_data)])


class RemoteOnOff(SofarEntity, SwitchEntity):
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:power"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "remote_on_off")

    @property
    def is_on(self):
        v = (self.coordinator.data or {}).get(self._key)
        return None if v is None else v == 1

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_remote_on(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_remote_on(False)
