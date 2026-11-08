"""Sensors."""
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
from .registers import SYS_STATES

M = SensorStateClass.MEASUREMENT
TI = SensorStateClass.TOTAL_INCREASING
DIAG = EntityCategory.DIAGNOSTIC


def _p(key, **kw):
    return SensorEntityDescription(key=key, device_class=SensorDeviceClass.POWER,
                                   native_unit_of_measurement=UnitOfPower.WATT, state_class=M, **kw)


def _v(key, **kw):
    return SensorEntityDescription(key=key, device_class=SensorDeviceClass.VOLTAGE,
                                   native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                                   state_class=M, suggested_display_precision=1, **kw)


def _a(key, **kw):
    return SensorEntityDescription(key=key, device_class=SensorDeviceClass.CURRENT,
                                   native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                                   state_class=M, suggested_display_precision=2, **kw)


def _e(key, **kw):
    return SensorEntityDescription(key=key, device_class=SensorDeviceClass.ENERGY,
                                   native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                                   state_class=TI, suggested_display_precision=2, **kw)


def _t(key, **kw):
    return SensorEntityDescription(key=key, device_class=SensorDeviceClass.TEMPERATURE,
                                   native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                                   state_class=M, **kw)


def _f(key, **kw):
    return SensorEntityDescription(key=key, device_class=SensorDeviceClass.FREQUENCY,
                                   native_unit_of_measurement=UnitOfFrequency.HERTZ,
                                   state_class=M, suggested_display_precision=2, **kw)


SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(key="sys_state_text", device_class=SensorDeviceClass.ENUM,
                            options=list(SYS_STATES.values())),
    # power
    _p("pv_power"), _p("pv1_power"), _p("pv2_power"),
    _p("grid_power"), _p("grid_import_power"), _p("grid_export_power"),
    _p("battery_power"), _p("battery_charge_power"), _p("battery_discharge_power"),
    _p("load_power"), _p("inverter_power"), _p("eps_power"),
    _p("pv_ext_power", entity_registry_enabled_default=False),
    # battery
    SensorEntityDescription(key="battery_soc", device_class=SensorDeviceClass.BATTERY,
                            native_unit_of_measurement=PERCENTAGE, state_class=M),
    SensorEntityDescription(key="battery_soh", native_unit_of_measurement=PERCENTAGE,
                            state_class=M, icon="mdi:battery-heart-variant"),
    SensorEntityDescription(key="battery_cycles", state_class=TI, icon="mdi:battery-sync"),
    _v("battery_voltage"), _a("battery_current"), _t("battery_temperature"),
    # PV / grid electrical
    _v("pv1_voltage"), _a("pv1_current"), _v("pv2_voltage"), _a("pv2_current"),
    _v("grid_voltage"), _a("grid_current"), _a("inverter_current"), _f("grid_frequency"),
    SensorEntityDescription(key="inverter_power_factor", device_class=SensorDeviceClass.POWER_FACTOR,
                            state_class=M, entity_registry_enabled_default=False),
    _v("eps_voltage", entity_registry_enabled_default=False),
    _f("eps_frequency", entity_registry_enabled_default=False),
    # energy
    _e("pv_energy_today"), _e("pv_energy_total"),
    _e("load_energy_today"), _e("load_energy_total"),
    _e("import_energy_today"), _e("import_energy_total"),
    _e("export_energy_today"), _e("export_energy_total"),
    _e("battery_charge_today"), _e("battery_charge_total"),
    _e("battery_discharge_today"), _e("battery_discharge_total"),
    # diagnostics
    _t("temp_inverter", entity_category=DIAG), _t("temp_heatsink", entity_category=DIAG),
    _t("temp_ambient", entity_category=DIAG),
    SensorEntityDescription(key="insulation_resistance", native_unit_of_measurement="kΩ",
                            state_class=M, entity_category=DIAG, icon="mdi:omega"),
    SensorEntityDescription(key="generation_time_today", device_class=SensorDeviceClass.DURATION,
                            native_unit_of_measurement=UnitOfTime.MINUTES, entity_category=DIAG),
    SensorEntityDescription(key="countdown", native_unit_of_measurement=UnitOfTime.SECONDS,
                            entity_category=DIAG, entity_registry_enabled_default=False),
    SensorEntityDescription(key="passive_grid_power", device_class=SensorDeviceClass.POWER,
                            native_unit_of_measurement=UnitOfPower.WATT, entity_category=DIAG,
                            entity_registry_enabled_default=False),
    SensorEntityDescription(key="inverter_clock", device_class=SensorDeviceClass.TIMESTAMP,
                            entity_category=DIAG),
    SensorEntityDescription(key="clock_drift", native_unit_of_measurement=UnitOfTime.SECONDS,
                            state_class=M, entity_category=DIAG, icon="mdi:clock-alert-outline"),
    SensorEntityDescription(key="serial", entity_category=DIAG),
    SensorEntityDescription(key="sw_version", entity_category=DIAG),
    SensorEntityDescription(key="sw_version_master", entity_category=DIAG,
                            entity_registry_enabled_default=False),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([SofarSensor(coordinator, d) for d in SENSORS] + [SlotScheduleSensor(coordinator)])


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
