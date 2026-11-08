"""Binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import SofarEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SofarFault(entry.runtime_data)])


class SofarFault(SofarEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "fault_active")

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get("fault_active")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {"faults": d.get("faults") or [], "unreadable_blocks": self.coordinator.failed_blocks}
