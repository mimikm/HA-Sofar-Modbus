# Sofar HYD-EP Modbus

Home Assistant integration for **Sofar HYD 3–6K-EP** hybrid inverters (e.g. HYD 3680-EP) over an **RS485-to-Ethernet gateway** such as the Ebyte NE2-D14E. Local polling, no cloud, no pymodbus dependency.

It reads the Sofar "new protocol" register map (0x0400+) and controls the battery through **passive mode**, which is how Sofar intends external energy managers to drive the inverter.

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mimikm&repository=HA-Sofar-Modbus&category=integration)
[![Validate](https://github.com/mimikm/HA-Sofar-Modbus/actions/workflows/validate.yml/badge.svg)](https://github.com/mimikm/HA-Sofar-Modbus/actions/workflows/validate.yml)

## Install

**HACS (recommended)**

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/mimikm/HA-Sofar-Modbus`, category **Integration** (or use the button above).
2. Download **Sofar HYD-EP Modbus**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → Sofar HYD-EP Modbus.**

**Manual**

Copy `custom_components/sofar_hyd_ep` into `/config/custom_components/` and restart Home Assistant.

## Gateway setup

| Setting | Value |
|---|---|
| Serial | 9600 baud, 8 data bits, no parity, 1 stop bit |
| Inverter Modbus address | 1 (check the inverter's display menu) |
| Network | TCP server, port 502 |

Pick the matching **Gateway protocol** when adding the integration:

* **Modbus TCP** – gateway is in Modbus TCP ↔ RTU conversion mode (recommended).
* **RTU over TCP** – gateway is in transparent / no-protocol mode.

If setup says "No answer from the inverter", try the other protocol option first, then check A/B wiring and the address.

Only one Modbus master should poll the inverter's RS485 port. Remove any other integration pointed at the same gateway.

## Entities

**Power (W):** PV, PV1, PV2, grid, grid import, grid export, battery, battery charge, battery discharge, house load, inverter AC, EPS.

**Battery:** SOC, SOH, cycles, voltage, current, temperature.

**Energy (kWh, Energy-dashboard ready):** PV, house load, grid import, grid export, battery charge, battery discharge – today and lifetime.

**Diagnostics:** inverter clock and drift, inverter state, fault (with fault bits as attributes), temperatures, insulation resistance, grid voltage/current/frequency, serial, firmware.

**Controls:**

| Entity | What it does |
|---|---|
| Energy storage mode | Self use / Time of use / Timing / Passive / Peak shaving |
| Battery action | Auto (self use), Force charge, Force discharge, Pause battery, Hold (no discharge) |
| Battery action power | Power used by Force charge / Force discharge |
| Passive desired grid power, minimum / maximum battery power | Raw passive-mode set-points |
| Passive timeout + action | Inverter falls back if it hears nothing for N seconds |
| Inverter on | Remote on/off (disabled by default) |
| Sync inverter clock | Sets the inverter clock to Home Assistant's local time |

### Sign conventions

| Value | Positive | Negative |
|---|---|---|
| Grid power sensor | exporting | importing |
| Battery power sensor | charging | discharging |
| Passive desired grid power | importing | exporting |
| Passive battery min/max | charging | discharging |

## Services

* `sofar_hyd_ep.battery_action` – `action` + optional `power`.
* `sofar_hyd_ep.set_passive` – `grid_power`, `battery_min`, `battery_max`. All three are written together in one Modbus frame, then the inverter is switched to passive mode.
* `sofar_hyd_ep.scan_registers` – reads every documented register range (or `start` + `count`) and saves a dump to `/config/sofar_register_scan_<time>.txt`. Use it to find registers your firmware supports that aren't mapped yet.

```yaml
# Force charge at 2.5 kW
service: sofar_hyd_ep.battery_action
data:
  action: Force charge
  power: 2500
```

## Options

* **Polling interval** – default 10 s.
* **Maximum battery power** – default 3000 W; caps the action power and sliders.
* **Keep inverter clock in sync** – auto-corrects drift over 30 s, at most once an hour.
* **Re-send passive set-points every poll** – turn on together with a passive timeout, so the inverter falls back safely if Home Assistant stops.

## Notes

* Register map: Sofar "Modbus Protocol – General, valid for HYD 5…20K-3PH and HYD 3…6K-EP". Passive-mode layout (0x1187 grid, 0x1189 min, 0x118B max, I32) matches what evcc and solax_modbus use on real hardware.
* Writes use function 0x10 only, as the protocol document specifies.
