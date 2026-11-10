# Predbat with Sofar Modbus

[Predbat](https://github.com/springfall2008/batpred) plans when to charge, discharge and hold your battery from your tariff, solar forecast and load history. This integration gives Predbat everything it needs to run a Sofar inverter, with no automations or helpers to write.

Works with every inverter the integration supports: HYD-EP, HYD-3PH and (beta) ME3000SP / HYD-ES.

## 1. Prepare the integration

In **Settings → Devices & services → Sofar Modbus → Configure**, set:

| Option | Why Predbat needs it |
|---|---|
| **Battery capacity (kWh)** | Gives `Battery stored energy` and `Battery capacity` (Predbat's `soc_kw` / `soc_max`). Use usable capacity, e.g. 4.8 for 2 × 2.4 kWh packs; lower it as the battery ages (see `Battery SOH`). |
| **Maximum battery power (W)** | Gives `Battery max power` (Predbat's `battery_rate_max`) and caps every charge/discharge command. |
| **Keep inverter clock in sync** | Recommended – Predbat plans in half-hour slots. |

Then check that these entities have values: `sensor.sofar_battery_soc`, `sensor.sofar_battery_stored_energy`, `sensor.sofar_battery_capacity`, `sensor.sofar_battery_max_power`.

**Legacy ME3000SP / HYD-ES:** set the inverter to **Passive mode** on its display and use **RTU over TCP** on the gateway. Comment out `inverter_time` in `apps.yaml` – these models have no readable clock.

## 2. Configure Predbat

Use [`apps.yaml`](apps.yaml) from this folder as your Predbat `apps.yaml`, or copy its inverter section (from `load_today` to `export_limit`) into your existing one. Then:

- Delete the `template: True` line.
- Set `inverter_limit` to your inverter's AC rating, e.g. 3680 for a HYD 3680-EP, and `export_limit` to your DNO limit.
- Set your tariff (Octopus, Kraken or rates) and Solcast as described in the [Predbat docs](https://springfall2008.github.io/batpred/).
- If you renamed the integration's device, replace the `sofar_` prefix in the entity names.

It uses Predbat's built-in **`SFMB`** (Sofar HYD) inverter profile, so no Predbat code changes are needed.

## How control works

Predbat calls the integration's `sofar_modbus.battery_action` service:

| Predbat wants to… | `operation` sent | What the inverter does |
|---|---|---|
| Charge to X % | `force_charge` + `power`, `target_soc` | Charges at `power` W until X %, then holds |
| Hold the charge | `freeze_charge` | Covers the house from grid/solar, battery never discharges, surplus solar still charges it |
| Export to X % | `force_discharge` + `power`, `target_soc` | Discharges at `power` W until X %, then holds |
| Freeze export | `freeze_discharge` | Battery may cover the house but never charges; surplus solar is exported |
| Go back to normal | `self_use` | Inverter's own self-use mode |

The service accepts the mode as `operation` or `action`, either as these short names or the full names shown in the Battery action select ("Auto (self use)", "Force charge", …).

The target-SOC stop runs inside the integration on every poll and survives restarts, so a missed Predbat cycle can't overcharge or over-discharge the battery.

Legacy inverters: "Hold (no discharge)" becomes standby and "Hold (no charge)" becomes auto, because the old protocol has no finer control.

## Tips

- Don't use the integration's **charge/discharge slots** or native **Timing/TOU** slots at the same time as Predbat – they would fight over the battery.
- Optional safety net (modern inverters): set **Passive timeout** to e.g. 600 s with action **Return to previous mode**, and turn on **Re-send passive set-points every poll**. If Home Assistant stops, the inverter falls back on its own.
- Multiple inverters (several Sofars, or Sofar + another brand): see below.

## Multiple inverters

Predbat runs **every** entry of a service list for **every** inverter – it does not pick the entry at the inverter's position. Predbat also skips a call that is identical to the previous one in the same domain, even when it came from the other inverter. So give each inverter its own device id and pass it through:

```yaml
  device_id:
  - <device id of inverter 0>
  - <device id of inverter 1>

  charge_start_service:
  - service: script.other_inverter_control   # e.g. a Solax script
    device_id: "{device_id}"
    operation: "Force Charge"
    power: "{power}"
  - service: sofar_modbus.battery_action
    device_id: "{device_id}"
    operation: force_charge
    power: "{power}"
    target_soc: "{target_soc}"
```

`battery_action` quietly ignores a call whose `device_id` is not a Sofar Modbus device, so each Sofar only acts on its own inverter's calls. (Find a device id in the URL of its device page.) Other brands' scripts need the same filter, e.g. a first step of `- condition: "{{ device_id is not defined or device_id == '<its device id>' }}"`.

With two batteries on one site meter, use `operation: hold_no_charge` (instead of `self_use`) as the Sofar's `charge_stop_service` action. Two batteries both in self-use can settle into one charging from the other while the grid reads 0 W.
