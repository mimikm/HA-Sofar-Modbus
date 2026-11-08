"""Remote on/off switch (disabled by default – it really turns the inverter off)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import SofarEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([RemoteOnOff(c)] + [NativeSwitch(c, k) for k in
                       ("timing_charge_enabled", "timing_discharge_enabled", "tou_enabled")])


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


class NativeSwitch(SofarEntity, SwitchEntity, RestoreEntity):
    """Local enable flag for native slot 1 / TOU rule 1 – written on Apply."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in ("on", "off"):
            self.coordinator.native[self._key] = last.state == "on"

    @property
    def is_on(self):
        return self.coordinator.native[self._key]

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.native[self._key] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.native[self._key] = False
        self.async_write_ha_state()
