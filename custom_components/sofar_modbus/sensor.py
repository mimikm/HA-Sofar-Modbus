"""Sensors – generated from the register table and filtered by the detected profile."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)

from .entity import SofarEntity
from .registers import LEGACY_STATES, SYS_STATES, table

M = SensorStateClass.MEASUREMENT
TI = SensorStateClass.TOTAL_INCREASING
DIAG = EntityCategory.DIAGNOSTIC

# kind -> SensorEntityDescription keyword arguments
KINDS: dict[str, dict] = {
    "power": dict(device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
                  state_class=M),
    "energy": dict(device_class=SensorDeviceClass.ENERGY,
                   native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=TI,
                   suggested_display_precision=2),
    "voltage": dict(device_class=SensorDeviceClass.VOLTAGE,
                    native_unit_of_measurement=UnitOfElectricPotential.VOLT, state_class=M,
                    suggested_display_precision=1),
    "current": dict(device_class=SensorDeviceClass.CURRENT,
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE, state_class=M,
                    suggested_display_precision=2),
    "current_ma": dict(device_class=SensorDeviceClass.CURRENT,
                       native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE, state_class=M),
    "temp": dict(device_class=SensorDeviceClass.TEMPERATURE,
                 native_unit_of_measurement=UnitOfTemperature.CELSIUS, state_class=M),
    "freq": dict(device_class=SensorDeviceClass.FREQUENCY,
                 native_unit_of_measurement=UnitOfFrequency.HERTZ, state_class=M,
                 suggested_display_precision=2),
    "pf": dict(device_class=SensorDeviceClass.POWER_FACTOR, state_class=M),
    "soc": dict(device_class=SensorDeviceClass.BATTERY, native_unit_of_measurement=PERCENTAGE,
                state_class=M),
    "pct": dict(native_unit_of_measurement=PERCENTAGE, state_class=M),
    "energy_storage": dict(device_class=SensorDeviceClass.ENERGY_STORAGE,
                           native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=M,
                           suggested_display_precision=2),
    "count": dict(state_class=TI),
    "duration_min": dict(device_class=SensorDeviceClass.DURATION,
                         native_unit_of_measurement=UnitOfTime.MINUTES),
    "duration_min_total": dict(device_class=SensorDeviceClass.DURATION,
                               native_unit_of_measurement=UnitOfTime.MINUTES, state_class=TI),
    "duration_s": dict(native_unit_of_measurement=UnitOfTime.SECONDS),
    "resistance": dict(native_unit_of_measurement="kΩ", state_class=M, icon="mdi:omega"),
}

# Derived sensors: (key, kind, required register keys (any of), extra kwargs)
DERIVED: list[tuple[str, str | None, tuple[str, ...], dict]] = [
    ("sys_state_text", None, ("sys_state",),
     dict(device_class=SensorDeviceClass.ENUM,
          options=list(dict.fromkeys([*SYS_STATES.values(), *LEGACY_STATES.values()])))),
    ("pv_power", "power", ("pv1_power", "pv_total_power_reg"), {}),
    ("grid_import_power", "power", ("grid_power",), {}),
    ("grid_export_power", "power", ("grid_power",), {}),
    ("battery_power", "power", ("battery1_power", "battery_total_power_reg"), {}),
    ("battery_charge_power", "power", ("battery1_power", "battery_total_power_reg"), {}),
    ("battery_discharge_power", "power", ("battery1_power", "battery_total_power_reg"), {}),
    ("battery_soc", "soc", ("battery1_soc", "battery_soc_avg_reg"), {}),
    ("battery_stored_energy", "energy_storage", ("battery1_soc", "battery_soc_avg_reg"), {}),
    ("battery_capacity", "energy_storage", ("battery1_soc", "battery_soc_avg_reg"),
     dict(state_class=None, icon="mdi:battery-high")),
    ("battery_max_power", "power", ("battery1_soc", "battery_soc_avg_reg"),
     dict(state_class=None, entity_category=DIAG)),
    ("battery_reserve", "pct", ("battery_dod",), dict(icon="mdi:battery-lock")),
    ("battery_eps_reserve", "pct", ("battery_eps_dod",),
     dict(icon="mdi:battery-lock", entity_category=DIAG, entity_registry_enabled_default=False)),
    ("inverter_clock", None, ("clock_year",),
     dict(device_class=SensorDeviceClass.TIMESTAMP, entity_category=DIAG)),
    ("clock_drift", None, ("clock_year",),
     dict(native_unit_of_measurement=UnitOfTime.SECONDS, state_class=M, entity_category=DIAG,
          icon="mdi:clock-alert-outline")),
    ("serial", None, (), dict(entity_category=DIAG)),
    ("sw_version", None, (), dict(entity_category=DIAG)),
    ("sw_version_master", None, (), dict(entity_category=DIAG, entity_registry_enabled_default=False)),
]


def descriptions(coordinator) -> list[SensorEntityDescription]:
    out = []
    for r in table(coordinator.family)["registers"]:
        if r.kind is None or not coordinator.has(r.key):
            continue
        kw = dict(KINDS[r.kind])
        if r.diag:
            kw["entity_category"] = DIAG
        if not r.enabled:
            kw["entity_registry_enabled_default"] = False
        out.append(SensorEntityDescription(key=r.key, **kw))
    for key, kind, needs, extra in DERIVED:
        if needs and not any(coordinator.has(n) for n in needs):
            continue
        kw = dict(KINDS[kind]) if kind else {}
        kw.update(extra)
        out.append(SensorEntityDescription(key=key, **kw))
    return out


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities: list[SensorEntity] = [SofarSensor(c, d) for d in descriptions(c)]
    if c.hybrid:
        entities.append(SlotScheduleSensor(c))
    async_add_entities(entities)


class SofarSensor(SofarEntity, SensorEntity):
    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._key)


class SlotScheduleSensor(SofarEntity, SensorEntity):
    """State = what the Home Assistant slot scheduler is doing; attributes list the slots."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "slot_schedule")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        return self.coordinator.slot_status

    @property
    def extra_state_attributes(self):
        return {"slots": self.coordinator.slots}
