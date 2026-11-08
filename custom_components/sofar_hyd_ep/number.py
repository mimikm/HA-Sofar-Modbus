"""Numbers: passive-mode set-points, battery action power, passive timeout."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.components.number import NumberEntity
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower, UnitOfTime

from .entity import SofarEntity

GRID_LIMIT = 10000  # W, sanity bound for the desired grid power slider


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    rated = c.max_battery_power
    async_add_entities([
        PassiveNumber(c, "passive_grid_power", -GRID_LIMIT, GRID_LIMIT),
        PassiveNumber(c, "passive_battery_min", -rated, rated),
        PassiveNumber(c, "passive_battery_max", -rated, rated),
        ActionPowerNumber(c),
        TimeoutNumber(c),
        NativeNumber(c, "timing_charge_power", 0, rated, 50, UnitOfPower.WATT),
        NativeNumber(c, "timing_discharge_power", 0, rated, 50, UnitOfPower.WATT),
        NativeNumber(c, "tou_power", 0, rated, 50, UnitOfPower.WATT),
        NativeNumber(c, "tou_target_soc", 30, 100, 1, PERCENTAGE),
    ])


class PassiveNumber(SofarEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_mode = NumberMode.BOX
    _attr_native_step = 10

    def __init__(self, coordinator, key, lo, hi) -> None:
        super().__init__(coordinator, key)
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_passive_value(self._key, int(value))


class ActionPowerNumber(SofarEntity, RestoreNumber):
    """Power used by the 'Battery action' select for force charge/discharge (local, not a register)."""

    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 50
    _attr_native_min_value = 0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "battery_action_power")
        self._attr_native_max_value = coordinator.max_battery_power

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self.coordinator.action_power = int(min(last.native_value, self.native_max_value))

    @property
    def native_value(self):
        return self.coordinator.action_power

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.action_power = int(value)
        self.async_write_ha_state()


class TimeoutNumber(SofarEntity, NumberEntity):
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 65535
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "passive_timeout")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_passive_timeout(seconds=int(value))


class NativeNumber(SofarEntity, RestoreNumber):
    """Local setting for native slot 1 / TOU rule 1 – written to the inverter on Apply."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key, lo, hi, step, unit) -> None:
        super().__init__(coordinator, key)
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self.coordinator.native[self._key] = int(last.native_value)

    @property
    def native_value(self):
        return self.coordinator.native[self._key]

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.native[self._key] = int(value)
        self.async_write_ha_state()
