"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import SofarCoordinator


class SofarEntity(CoordinatorEntity[SofarCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SofarCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        entry = coordinator.config_entry
        uid = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{uid}_{key}"
        self._attr_translation_key = key
        data = coordinator.data or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uid)},
            manufacturer=MANUFACTURER,
            model="HYD-EP hybrid inverter",
            name=entry.title,
            serial_number=data.get("serial") or None,
            sw_version=data.get("sw_version"),
            hw_version=data.get("hw_version") or None,
        )

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data or {}).get(self._key) is not None
