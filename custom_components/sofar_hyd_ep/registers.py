"""Sofar HYD 3-6K-EP register map (Sofar "Modbus Protocol - General", new 0x0400+ map).

Pure Python, no Home Assistant imports, so it can be unit tested.

Conventions from the Sofar protocol document:
* Read with FC 0x03, write with FC 0x10 only.
* 32-bit values are big-endian, high word first.
* Battery power/current: + charge, - discharge.
* PCC (grid) power: + export to grid, - import from grid.
* Passive-mode registers (0x1187..0x118C, three I32) are written together.
"""
from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- blocks
# (name, start, count, poll) – poll=False means read once at start-up / on demand.
BLOCKS: list[tuple[str, int, int, bool]] = [
    ("system", 0x0404, 0x28, True),     # 0x0404..0x042B state, faults, temps
    ("grid", 0x0484, 0x2C, True),       # 0x0484..0x04AF grid / PCC / load
    ("eps", 0x0504, 0x07, True),        # 0x0504..0x050A off-grid output
    ("pv", 0x0584, 0x06, True),         # 0x0584..0x0589 PV1/PV2
    ("battery", 0x0604, 0x07, True),    # 0x0604..0x060A battery 1
    ("energy", 0x0684, 0x18, True),     # 0x0684..0x069B energy counters
    ("remote", 0x1104, 0x01, True),     # remote on/off
    ("mode", 0x1110, 0x01, True),       # energy storage mode
    ("passive_to", 0x1184, 0x02, True),  # passive timeout + action
    ("passive", 0x1187, 0x06, True),    # passive grid / min / max (3x I32)
    ("info_sn", 0x0445, 0x07, False),   # 0x0445..0x044B serial number
    ("info_fw", 0x044D, 0x0A, False),   # 0x044D..0x0456 hardware + firmware
]

# Ranges dumped by the "scan registers" service (start, end inclusive).
SCAN_RANGES: list[tuple[int, int]] = [
    (0x0400, 0x047F),
    (0x0480, 0x04BF),
    (0x0500, 0x053F),
    (0x0580, 0x05FF),
    (0x0600, 0x06FF),
    (0x1000, 0x1053),
    (0x1100, 0x11C5),
]


@dataclass(frozen=True)
class Reg:
    key: str
    address: int
    dtype: str = "u16"      # u16 | i16 | u32 | i32
    scale: float = 1.0

    @property
    def size(self) -> int:
        return 2 if self.dtype in ("u32", "i32") else 1


KW_TO_W = 10.0  # 0.01 kW register unit -> W

REGISTERS: list[Reg] = [
    # system
    Reg("sys_state", 0x0404),
    Reg("countdown", 0x0417),
    Reg("temp_ambient", 0x0418, "i16"),
    Reg("temp_heatsink", 0x041A, "i16"),
    Reg("temp_inverter", 0x0420, "i16"),
    Reg("generation_time_today", 0x0426),
    Reg("insulation_resistance", 0x042B),
    # grid / PCC
    Reg("grid_frequency", 0x0484, "u16", 0.01),
    Reg("inverter_power", 0x0485, "i16", KW_TO_W),
    Reg("grid_power", 0x0488, "i16", KW_TO_W),
    Reg("grid_voltage", 0x048D, "u16", 0.1),
    Reg("inverter_current", 0x048E, "u16", 0.01),
    Reg("inverter_power_factor", 0x0491, "i16", 0.001),
    Reg("grid_current", 0x0492, "u16", 0.01),
    Reg("pv_ext_power", 0x04AE, "u16", KW_TO_W),
    Reg("load_power", 0x04AF, "u16", KW_TO_W),
    # EPS / off-grid output
    Reg("eps_power", 0x0504, "i16", KW_TO_W),
    Reg("eps_frequency", 0x0507, "u16", 0.01),
    Reg("eps_voltage", 0x050A, "u16", 0.1),
    # PV
    Reg("pv1_voltage", 0x0584, "u16", 0.1),
    Reg("pv1_current", 0x0585, "u16", 0.01),
    Reg("pv1_power", 0x0586, "u16", KW_TO_W),
    Reg("pv2_voltage", 0x0587, "u16", 0.1),
    Reg("pv2_current", 0x0588, "u16", 0.01),
    Reg("pv2_power", 0x0589, "u16", KW_TO_W),
    # battery
    Reg("battery_voltage", 0x0604, "u16", 0.1),
    Reg("battery_current", 0x0605, "i16", 0.01),
    Reg("battery_power", 0x0606, "i16", KW_TO_W),
    Reg("battery_temperature", 0x0607, "i16"),
    Reg("battery_soc", 0x0608),
    Reg("battery_soh", 0x0609),
    Reg("battery_cycles", 0x060A),
    # energy counters
    Reg("pv_energy_today", 0x0684, "u32", 0.01),
    Reg("pv_energy_total", 0x0686, "u32", 0.1),
    Reg("load_energy_today", 0x0688, "u32", 0.01),
    Reg("load_energy_total", 0x068A, "u32", 0.1),
    Reg("import_energy_today", 0x068C, "u32", 0.01),
    Reg("import_energy_total", 0x068E, "u32", 0.1),
    Reg("export_energy_today", 0x0690, "u32", 0.01),
    Reg("export_energy_total", 0x0692, "u32", 0.1),
    Reg("battery_charge_today", 0x0694, "u32", 0.01),
    Reg("battery_charge_total", 0x0696, "u32", 0.1),
    Reg("battery_discharge_today", 0x0698, "u32", 0.01),
    Reg("battery_discharge_total", 0x069A, "u32", 0.1),
    # control read-back
    Reg("remote_on_off", 0x1104),
    Reg("energy_storage_mode", 0x1110),
    Reg("passive_timeout", 0x1184),
    Reg("passive_timeout_action", 0x1185),
    Reg("passive_grid_power", 0x1187, "i32"),
    Reg("passive_battery_min", 0x1189, "i32"),
    Reg("passive_battery_max", 0x118B, "i32"),
]

FAULT_RANGE = (0x0405, 0x0416)  # Fault1..Fault18


def known_runs(start: int, count: int) -> list[tuple[int, int]]:
    """Contiguous runs of documented registers inside a block (fallback reads)."""
    end = start + count
    wanted: set[int] = set()
    for reg in REGISTERS:
        for a in range(reg.address, reg.address + reg.size):
            if start <= a < end:
                wanted.add(a)
    for a in range(FAULT_RANGE[0], FAULT_RANGE[1] + 1):
        if start <= a < end:
            wanted.add(a)
    if start == 0x0445:
        wanted.update(range(0x0445, 0x044C))
    if start == 0x044D:
        wanted.update(range(0x044D, 0x0457))
    runs: list[tuple[int, int]] = []
    for a in sorted(wanted):
        if runs and runs[-1][0] + runs[-1][1] == a:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((a, 1))
    return runs

# --------------------------------------------------------------------------- enums
SYS_STATES = {
    0: "Waiting",
    1: "Checking",
    2: "On grid",
    3: "EPS",
    4: "Fault",
    5: "Permanent fault",
    6: "Updating firmware",
    7: "Self charging",
}

STORAGE_MODES = {
    0: "Self use",
    1: "Time of use",
    2: "Timing",
    3: "Passive",
    4: "Peak shaving",
}

TIMEOUT_ACTIONS = {
    0: "Standby",
    1: "Return to previous mode",
}

# Control registers
REG_REMOTE_ON_OFF = 0x1104
REG_STORAGE_MODE = 0x1110
REG_PASSIVE_TIMEOUT = 0x1184
REG_PASSIVE_BLOCK = 0x1187
MODE_SELF_USE = 0
MODE_PASSIVE = 3


# --------------------------------------------------------------------------- helpers
def to_signed16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def pack_i32(value: int) -> list[int]:
    value = int(value) & 0xFFFFFFFF
    return [value >> 16, value & 0xFFFF]


def pack_passive(grid: int, bmin: int, bmax: int) -> list[int]:
    return pack_i32(grid) + pack_i32(bmin) + pack_i32(bmax)


def _ascii(words: list[int]) -> str:
    out = bytearray()
    for w in words:
        out += bytes([(w >> 8) & 0xFF, w & 0xFF])
    return out.replace(b"\x00", b"").decode("ascii", "replace").strip()


def decode(raw: dict[int, int]) -> dict:
    """Turn {address: word} into {key: value}. Missing registers -> None."""
    data: dict = {}
    for reg in REGISTERS:
        hi = raw.get(reg.address)
        if hi is None or (reg.size == 2 and raw.get(reg.address + 1) is None):
            data[reg.key] = None
            continue
        if reg.dtype == "u16":
            val = hi
        elif reg.dtype == "i16":
            val = to_signed16(hi)
        else:
            val = (hi << 16) | raw[reg.address + 1]
            if reg.dtype == "i32" and val & 0x80000000:
                val -= 0x100000000
        if reg.scale != 1.0:
            val = round(val * reg.scale, 3)
        data[reg.key] = val

    # Faults: list of "FaultN bitB" for every set bit.
    faults = []
    have_faults = False
    for idx, addr in enumerate(range(FAULT_RANGE[0], FAULT_RANGE[1] + 1), start=1):
        word = raw.get(addr)
        if word is None:
            continue
        have_faults = True
        for bit in range(16):
            if word & (1 << bit):
                faults.append(f"Fault{idx} bit{bit}")
    data["faults"] = faults if have_faults else None
    data["fault_active"] = bool(faults) if have_faults else None

    # Derived
    st = data.get("sys_state")
    data["sys_state_text"] = SYS_STATES.get(st) if st is not None else None
    m = data.get("energy_storage_mode")
    data["energy_storage_mode_text"] = STORAGE_MODES.get(m) if m is not None else None
    a = data.get("passive_timeout_action")
    data["passive_timeout_action_text"] = TIMEOUT_ACTIONS.get(a) if a is not None else None

    p1, p2 = data.get("pv1_power"), data.get("pv2_power")
    data["pv_power"] = None if p1 is None and p2 is None else (p1 or 0) + (p2 or 0)

    g = data.get("grid_power")
    data["grid_export_power"] = None if g is None else max(g, 0)
    data["grid_import_power"] = None if g is None else max(-g, 0)

    b = data.get("battery_power")
    data["battery_charge_power"] = None if b is None else max(b, 0)
    data["battery_discharge_power"] = None if b is None else max(-b, 0)

    if 0x0445 in raw:
        data["serial"] = _ascii([raw.get(a, 0) for a in range(0x0445, 0x044C)])
        data["hw_version"] = _ascii([raw.get(a, 0) for a in (0x044D, 0x044E)])
        data["sw_version"] = _sw(raw, 0x044F)
        data["sw_version_master"] = _sw(raw, 0x0453)
    data["battery_action"] = battery_action(data)
    return data


def _sw(raw: dict[int, int], base: int) -> str | None:
    words = [raw.get(base + i) for i in range(4)]
    if any(w is None for w in words):
        return None
    stage = chr(words[0] & 0xFF) if 32 <= (words[0] & 0xFF) < 127 else ""
    return f"{stage}{words[1]:04X}-{words[2]:04X}-{words[3]:04X}"


# Battery action presets ------------------------------------------------------
ACTION_AUTO = "Auto (self use)"
ACTION_CHARGE = "Force charge"
ACTION_DISCHARGE = "Force discharge"
ACTION_PAUSE = "Pause battery"
ACTION_NO_DISCHARGE = "Hold (no discharge)"
ACTION_PASSIVE_CUSTOM = "Passive (custom)"
ACTION_OTHER = "Inverter mode"

BATTERY_ACTIONS = [ACTION_AUTO, ACTION_CHARGE, ACTION_DISCHARGE, ACTION_PAUSE,
                   ACTION_NO_DISCHARGE]


def battery_action(data: dict) -> str | None:
    mode = data.get("energy_storage_mode")
    if mode is None:
        return None
    if mode == MODE_SELF_USE:
        return ACTION_AUTO
    if mode != MODE_PASSIVE:
        return ACTION_OTHER
    lo, hi = data.get("passive_battery_min"), data.get("passive_battery_max")
    if lo is None or hi is None:
        return ACTION_PASSIVE_CUSTOM
    if lo == hi == 0:
        return ACTION_PAUSE
    if lo == hi and lo > 0:
        return ACTION_CHARGE
    if lo == hi and lo < 0:
        return ACTION_DISCHARGE
    if lo == 0 and hi > 0:
        return ACTION_NO_DISCHARGE
    return ACTION_PASSIVE_CUSTOM


def action_to_passive(action: str, power: int, rated: int) -> tuple[int, int, int] | None:
    """Return (grid, min, max) for a passive preset, or None for 'Auto'."""
    power = abs(int(power))
    if action == ACTION_CHARGE:
        return 0, power, power
    if action == ACTION_DISCHARGE:
        return 0, -power, -power
    if action == ACTION_PAUSE:
        return 0, 0, 0
    if action == ACTION_NO_DISCHARGE:
        # Grid target 0, battery may only charge (from surplus), never discharge.
        return 0, 0, rated
    return None
