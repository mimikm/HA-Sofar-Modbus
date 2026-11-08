"""Sofar register map – modern ("G3", 0x0400+) protocol.

Covers HYD 3-6K-EP, HYD 5-20K-3PH, KTL-X G3 / KTLM PV inverters and ZCS Azzurro
rebadges. Pure Python, no Home Assistant imports, so it can be unit tested.

Conventions from the Sofar protocol document:
* Read with FC 0x03, write with FC 0x10 only.
* 32-bit values are big-endian, high word first.
* Battery power/current: + charge, - discharge.
* PCC (grid) power: + export to grid, - import from grid.
* The first 4 registers of every 64-register field are an address mask (U64):
  bit n set = register field_base + n is implemented on this inverter.
"""
from __future__ import annotations

from dataclasses import dataclass

# Ranges dumped by the "scan registers" service and diagnostics (start, end inclusive).
SCAN_RANGES: list[tuple[int, int]] = [
    (0x0400, 0x047F),
    (0x0480, 0x04BF),
    (0x0500, 0x053F),
    (0x0580, 0x05FF),
    (0x0600, 0x06FF),
    (0x1000, 0x1053),
    (0x1100, 0x11C5),
]

# Real-time fields that carry an address mask in their first 4 registers.
MASK_FIELDS = [0x0400, 0x0480, 0x0500, 0x0580, 0x05C0, 0x0600, 0x0640, 0x0680, 0x06C0]

INFO_RANGES = [(0x0445, 7), (0x044D, 10)]       # serial, hardware + firmware
REG_INPUT_CHANNELS = 0x1011                      # 16 x InputType_ChannelN_Config


@dataclass(frozen=True)
class Reg:
    key: str
    address: int
    dtype: str = "u16"      # u16 | i16 | u32 | i32
    scale: float = 1.0
    kind: str | None = None  # sensor kind (see sensor.py); None = not a sensor of its own
    name: str = ""
    group: str = "core"      # core | grid3 | eps3 | pv1..pv4 | pvtotal | battery | battery2 |
                             # battery_total | hybrid | internal | clock | optional
    enabled: bool = True     # entity enabled by default
    diag: bool = False       # diagnostic entity category

    @property
    def size(self) -> int:
        return 2 if self.dtype in ("u32", "i32") else 1


KW_TO_W = 10.0     # 0.01 kW -> W
KW1_TO_W = 100.0   # 0.1 kW -> W

R = Reg
REGISTERS: list[Reg] = [
    # ---- system
    R("sys_state", 0x0404),
    R("countdown", 0x0417, kind="duration_s", name="Countdown", enabled=False, diag=True),
    R("temp_ambient", 0x0418, "i16", kind="temp", name="Ambient temperature", diag=True),
    R("temp_ambient2", 0x0419, "i16", kind="temp", name="Ambient temperature 2", group="optional", diag=True),
    R("temp_heatsink", 0x041A, "i16", kind="temp", name="Heatsink temperature", diag=True),
    R("temp_heatsink2", 0x041B, "i16", kind="temp", name="Heatsink temperature 2", group="optional", diag=True),
    R("temp_inverter", 0x0420, "i16", kind="temp", name="Inverter temperature", diag=True),
    R("temp_inverter2", 0x0421, "i16", kind="temp", name="Inverter temperature 2", group="optional", diag=True),
    R("generation_time_today", 0x0426, kind="duration_min", name="Generation time today", diag=True),
    R("generation_time_total", 0x0427, "u32", kind="duration_min_total", name="Generation time total",
      group="optional", diag=True, enabled=False),
    R("insulation_resistance", 0x042B, kind="resistance", name="Insulation resistance", diag=True),
    R("clock_year", 0x042C, group="clock"),
    R("clock_month", 0x042D, group="clock"),
    R("clock_day", 0x042E, group="clock"),
    R("clock_hour", 0x042F, group="clock"),
    R("clock_minute", 0x0430, group="clock"),
    R("clock_second", 0x0431, group="clock"),
    # ---- grid / PCC (phase R = single phase)
    R("grid_frequency", 0x0484, "u16", 0.01, kind="freq", name="Grid frequency"),
    R("inverter_power", 0x0485, "i16", KW_TO_W, kind="power", name="Inverter AC power"),
    R("grid_power", 0x0488, "i16", KW_TO_W, kind="power", name="Grid power"),
    R("grid_voltage", 0x048D, "u16", 0.1, kind="voltage", name="Grid voltage"),
    R("inverter_current", 0x048E, "u16", 0.01, kind="current", name="Inverter current"),
    R("inverter_power_factor", 0x0491, "i16", 0.001, kind="pf", name="Inverter power factor", enabled=False),
    R("grid_current", 0x0492, "u16", 0.01, kind="current", name="Grid current"),
    # three-phase extras
    R("inverter_power_r", 0x048F, "i16", KW_TO_W, kind="power", name="Inverter power L1", group="grid3"),
    R("grid_power_r", 0x0493, "i16", KW_TO_W, kind="power", name="Grid power L1", group="grid3"),
    R("grid_voltage_s", 0x0498, "u16", 0.1, kind="voltage", name="Grid voltage L2", group="grid3"),
    R("inverter_current_s", 0x0499, "u16", 0.01, kind="current", name="Inverter current L2", group="grid3"),
    R("inverter_power_s", 0x049A, "i16", KW_TO_W, kind="power", name="Inverter power L2", group="grid3"),
    R("grid_current_s", 0x049D, "u16", 0.01, kind="current", name="Grid current L2", group="grid3"),
    R("grid_power_s", 0x049E, "i16", KW_TO_W, kind="power", name="Grid power L2", group="grid3"),
    R("grid_voltage_t", 0x04A3, "u16", 0.1, kind="voltage", name="Grid voltage L3", group="grid3"),
    R("inverter_current_t", 0x04A4, "u16", 0.01, kind="current", name="Inverter current L3", group="grid3"),
    R("inverter_power_t", 0x04A5, "i16", KW_TO_W, kind="power", name="Inverter power L3", group="grid3"),
    R("grid_current_t", 0x04A8, "u16", 0.01, kind="current", name="Grid current L3", group="grid3"),
    R("grid_power_t", 0x04A9, "i16", KW_TO_W, kind="power", name="Grid power L3", group="grid3"),
    R("pv_ext_power", 0x04AE, "u16", KW_TO_W, kind="power", name="External PV power", enabled=False),
    R("load_power", 0x04AF, "u16", KW_TO_W, kind="power", name="House load power"),
    # ---- EPS / off-grid output
    R("eps_power", 0x0504, "i16", KW_TO_W, kind="power", name="EPS power", group="hybrid"),
    R("eps_frequency", 0x0507, "u16", 0.01, kind="freq", name="EPS frequency", group="hybrid", enabled=False),
    R("eps_voltage", 0x050A, "u16", 0.1, kind="voltage", name="EPS voltage", group="hybrid", enabled=False),
    R("eps_power_r", 0x050C, "i16", KW_TO_W, kind="power", name="EPS power L1", group="eps3", enabled=False),
    R("eps_voltage_s", 0x0512, "u16", 0.1, kind="voltage", name="EPS voltage L2", group="eps3", enabled=False),
    R("eps_power_s", 0x0514, "i16", KW_TO_W, kind="power", name="EPS power L2", group="eps3", enabled=False),
    R("eps_voltage_t", 0x051A, "u16", 0.1, kind="voltage", name="EPS voltage L3", group="eps3", enabled=False),
    R("eps_power_t", 0x051C, "i16", KW_TO_W, kind="power", name="EPS power L3", group="eps3", enabled=False),
    # ---- PV inputs
    R("pv1_voltage", 0x0584, "u16", 0.1, kind="voltage", name="PV1 voltage", group="pv1"),
    R("pv1_current", 0x0585, "u16", 0.01, kind="current", name="PV1 current", group="pv1"),
    R("pv1_power", 0x0586, "u16", KW_TO_W, kind="power", name="PV1 power", group="pv1"),
    R("pv2_voltage", 0x0587, "u16", 0.1, kind="voltage", name="PV2 voltage", group="pv2"),
    R("pv2_current", 0x0588, "u16", 0.01, kind="current", name="PV2 current", group="pv2"),
    R("pv2_power", 0x0589, "u16", KW_TO_W, kind="power", name="PV2 power", group="pv2"),
    R("pv3_voltage", 0x058A, "u16", 0.1, kind="voltage", name="PV3 voltage", group="pv3"),
    R("pv3_current", 0x058B, "u16", 0.01, kind="current", name="PV3 current", group="pv3"),
    R("pv3_power", 0x058C, "u16", KW_TO_W, kind="power", name="PV3 power", group="pv3"),
    R("pv4_voltage", 0x058D, "u16", 0.1, kind="voltage", name="PV4 voltage", group="pv4"),
    R("pv4_current", 0x058E, "u16", 0.01, kind="current", name="PV4 current", group="pv4"),
    R("pv4_power", 0x058F, "u16", KW_TO_W, kind="power", name="PV4 power", group="pv4"),
    R("pv_total_power_reg", 0x05C4, "u16", KW1_TO_W, group="pvtotal"),
    # ---- battery input 1
    R("battery_voltage", 0x0604, "u16", 0.1, kind="voltage", name="Battery voltage", group="battery"),
    R("battery_current", 0x0605, "i16", 0.01, kind="current", name="Battery current", group="battery"),
    R("battery1_power", 0x0606, "i16", KW_TO_W, group="battery"),
    R("battery_temperature", 0x0607, "i16", kind="temp", name="Battery temperature", group="battery"),
    R("battery1_soc", 0x0608, group="battery"),
    R("battery_soh", 0x0609, kind="pct", name="Battery SOH", group="battery"),
    R("battery_cycles", 0x060A, kind="count", name="Battery cycles", group="battery"),
    # ---- battery input 2 (three-phase hybrids)
    R("battery2_voltage", 0x060B, "u16", 0.1, kind="voltage", name="Battery 2 voltage", group="battery2"),
    R("battery2_current", 0x060C, "i16", 0.01, kind="current", name="Battery 2 current", group="battery2"),
    R("battery2_power", 0x060D, "i16", KW_TO_W, kind="power", name="Battery 2 power", group="battery2"),
    R("battery2_temperature", 0x060E, "i16", kind="temp", name="Battery 2 temperature", group="battery2"),
    R("battery2_soc", 0x060F, kind="soc", name="Battery 2 SOC", group="battery2"),
    R("battery2_soh", 0x0610, kind="pct", name="Battery 2 SOH", group="battery2"),
    R("battery2_cycles", 0x0611, kind="count", name="Battery 2 cycles", group="battery2"),
    # battery totals (newer firmware; only used when the address mask confirms them)
    R("battery_total_power_reg", 0x0667, "i16", KW1_TO_W, group="battery_total"),
    R("battery_soc_avg_reg", 0x0668, group="battery_total"),
    # ---- energy counters
    R("pv_energy_today", 0x0684, "u32", 0.01, kind="energy", name="PV energy today"),
    R("pv_energy_total", 0x0686, "u32", 0.1, kind="energy", name="PV energy total"),
    R("load_energy_today", 0x0688, "u32", 0.01, kind="energy", name="House load energy today"),
    R("load_energy_total", 0x068A, "u32", 0.1, kind="energy", name="House load energy total"),
    R("import_energy_today", 0x068C, "u32", 0.01, kind="energy", name="Grid import today"),
    R("import_energy_total", 0x068E, "u32", 0.1, kind="energy", name="Grid import total"),
    R("export_energy_today", 0x0690, "u32", 0.01, kind="energy", name="Grid export today"),
    R("export_energy_total", 0x0692, "u32", 0.1, kind="energy", name="Grid export total"),
    R("battery_charge_today", 0x0694, "u32", 0.01, kind="energy", name="Battery charge today", group="battery"),
    R("battery_charge_total", 0x0696, "u32", 0.1, kind="energy", name="Battery charge total", group="battery"),
    R("battery_discharge_today", 0x0698, "u32", 0.01, kind="energy", name="Battery discharge today", group="battery"),
    R("battery_discharge_total", 0x069A, "u32", 0.1, kind="energy", name="Battery discharge total", group="battery"),
    # ---- internal (installer) values
    R("gfci_current", 0x06C4, kind="current_ma", name="Residual current (GFCI)", group="internal",
      enabled=False, diag=True),
    R("bus_voltage", 0x06CC, "u16", 0.1, kind="voltage", name="DC bus voltage", group="internal",
      enabled=False, diag=True),
    # ---- control read-back (hybrids)
    R("remote_on_off", 0x1104, group="core"),
    R("energy_storage_mode", 0x1110, group="hybrid"),
    R("passive_timeout", 0x1184, group="hybrid"),
    R("passive_timeout_action", 0x1185, group="hybrid"),
    R("passive_grid_power", 0x1187, "i32", kind="power", name="Passive desired grid power (read-back)",
      group="hybrid", enabled=False, diag=True),
    R("passive_battery_min", 0x1189, "i32", group="hybrid"),
    R("passive_battery_max", 0x118B, "i32", group="hybrid"),
]
del R

REG_BY_KEY: dict[str, Reg] = {r.key: r for r in REGISTERS}
FAULT_RANGE = (0x0405, 0x0416)  # Fault1..Fault18

# --------------------------------------------------------------------------- legacy storage map
# ME3000SP / HYD 3-6K-ES ("ModBus-RTU protocol ME3000SP" v1.04). Same sign
# conventions as the modern map: battery + = charging, grid + = exporting.
# Keys reuse the modern names so entities, translations and derived values match.
L = Reg
LEGACY_REGISTERS: list[Reg] = [
    L("sys_state", 0x0200),
    L("grid_voltage", 0x0206, "u16", 0.1, kind="voltage", name="Grid voltage"),
    L("grid_current", 0x0207, "i16", 0.01, kind="current", name="Grid current"),
    L("grid_frequency", 0x020C, "u16", 0.01, kind="freq", name="Grid frequency"),
    L("battery1_power", 0x020D, "i16", KW_TO_W, group="battery"),
    L("battery_voltage", 0x020E, "u16", 0.1, kind="voltage", name="Battery voltage", group="battery"),
    L("battery_current", 0x020F, "i16", 0.01, kind="current", name="Battery current", group="battery"),
    L("battery1_soc", 0x0210, group="battery"),
    L("battery_temperature", 0x0211, "i16", kind="temp", name="Battery temperature", group="battery"),
    L("grid_power", 0x0212, "i16", KW_TO_W, kind="power", name="Grid power"),
    L("load_power", 0x0213, "u16", KW_TO_W, kind="power", name="House load power"),
    L("inverter_power", 0x0214, "i16", KW_TO_W, kind="power", name="Inverter AC power"),
    L("pv_total_power_reg", 0x0215, "u16", KW_TO_W, group="pvtotal"),
    L("eps_voltage", 0x0216, "u16", 0.1, kind="voltage", name="EPS voltage", enabled=False),
    L("eps_power", 0x0217, "u16", KW_TO_W, kind="power", name="EPS power"),
    L("pv_energy_today", 0x0218, "u16", 0.01, kind="energy", name="PV energy today"),
    L("export_energy_today", 0x0219, "u16", 0.01, kind="energy", name="Grid export today"),
    L("import_energy_today", 0x021A, "u16", 0.01, kind="energy", name="Grid import today"),
    L("load_energy_today", 0x021B, "u16", 0.01, kind="energy", name="House load energy today"),
    L("pv_energy_total", 0x021C, "u32", 1.0, kind="energy", name="PV energy total"),
    L("export_energy_total", 0x021E, "u32", 1.0, kind="energy", name="Grid export total"),
    L("import_energy_total", 0x0220, "u32", 1.0, kind="energy", name="Grid import total"),
    L("load_energy_total", 0x0222, "u32", 1.0, kind="energy", name="House load energy total"),
    L("countdown", 0x022A, kind="duration_s", name="Countdown", enabled=False, diag=True),
    L("battery_cycles", 0x022C, kind="count", name="Battery cycles", group="battery"),
    L("battery_soh", 0x0237, kind="pct", name="Battery SOH", group="battery"),
    L("temp_inverter", 0x0238, "i16", kind="temp", name="Inverter temperature", diag=True),
    L("temp_heatsink", 0x0239, "i16", kind="temp", name="Heatsink temperature", diag=True),
    L("generation_time_today", 0x0243, kind="duration_min", name="Generation time today", diag=True),
    L("pv1_voltage", 0x0250, "u16", 0.1, kind="voltage", name="PV1 voltage", group="pv1"),
    L("pv1_current", 0x0251, "u16", 0.01, kind="current", name="PV1 current", group="pv1"),
    L("pv1_power", 0x0252, "u16", KW_TO_W, kind="power", name="PV1 power", group="pv1"),
    L("pv2_voltage", 0x0253, "u16", 0.1, kind="voltage", name="PV2 voltage", group="pv2"),
    L("pv2_current", 0x0254, "u16", 0.01, kind="current", name="PV2 current", group="pv2"),
    L("pv2_power", 0x0255, "u16", KW_TO_W, kind="power", name="PV2 power", group="pv2"),
]
del L

LEGACY_STATES = {
    0: "Waiting",
    1: "Checking charge",
    2: "Charging",
    3: "Checking discharge",
    4: "Discharging",
    5: "EPS",
    6: "Fault",
    7: "Permanent fault",
}

# Passive commands (non-standard function code 0x42; inverter must be set to
# Passive mode on its own display).
LEGACY_FC_PASSIVE = 0x42
LEGACY_CMD_STANDBY = 0x0100   # value 0x5555
LEGACY_CMD_DISCHARGE = 0x0101  # value = W
LEGACY_CMD_CHARGE = 0x0102     # value = W
LEGACY_CMD_AUTO = 0x0103       # value 0
LEGACY_STANDBY_VALUE = 0x5555

FAMILY_TABLES: dict[str, dict] = {}

# Registers every modern Sofar must answer; used when masks are unavailable.
CORE_GROUPS = {"core", "clock"}


def table(family: str = "modern") -> dict:
    return FAMILY_TABLES[family]


def reg_addresses(keys, family: str = "modern") -> set[int]:
    t = table(family)
    out: set[int] = set()
    for k in keys:
        r = t["by_key"].get(k)
        if r:
            out.update(range(r.address, r.address + r.size))
    if "sys_state" in keys:
        out.update(range(t["faults"][0], t["faults"][1] + 1))
    return out


def runs(addresses, max_gap: int = 6, max_len: int = 40) -> list[tuple[int, int]]:
    """Group addresses into contiguous read runs, bridging small gaps."""
    out: list[tuple[int, int]] = []
    for a in sorted(set(addresses)):
        if out:
            start, count = out[-1]
            end = start + count
            same_field = (start & ~0x3F) == (a & ~0x3F)
            if a < end:
                continue
            if a - end <= max_gap and a - start < max_len and same_field:
                out[-1] = (start, a - start + 1)
                continue
        out.append((a, 1))
    return out


def make_blocks(keys, family: str = "modern") -> tuple[list[tuple[str, int, int, bool]], dict[str, set[int]]]:
    """Polling blocks + the addresses each block actually needs (for fallback reads)."""
    wanted = reg_addresses(keys, family)
    blocks, need = [], {}
    for start, count in runs(wanted):
        name = f"0x{start:04X}"
        blocks.append((name, start, count, True))
        need[name] = {a for a in wanted if start <= a < start + count}
    for start, count in table(family)["info"]:
        name = f"info_0x{start:04X}"
        blocks.append((name, start, count, False))
        need[name] = set(range(start, start + count))
    return blocks, need


def known_runs(start: int, count: int, wanted: set[int] | None = None) -> list[tuple[int, int]]:
    """Contiguous runs of needed registers inside a block (fallback reads)."""
    if wanted is None:
        wanted = {a for a in reg_addresses([r.key for r in REGISTERS]) if start <= a < start + count}
        for s0, c0 in INFO_RANGES:
            if start == s0:
                wanted = set(range(s0, s0 + c0))
    return runs(wanted, max_gap=0, max_len=1000)


FAMILY_TABLES.update({
    "modern": {"registers": REGISTERS, "by_key": REG_BY_KEY, "faults": FAULT_RANGE,
               "info": INFO_RANGES, "scan": SCAN_RANGES},
    "legacy_storage": {"registers": LEGACY_REGISTERS,
                       "by_key": {r.key: r for r in LEGACY_REGISTERS},
                       "faults": (0x0201, 0x0205),
                       "info": [(0x2001, 7), (0x2008, 4)],
                       "scan": [(0x0200, 0x0245), (0x0250, 0x0255), (0x1040, 0x1042),
                                (0x10B0, 0x10BC), (0x2000, 0x200B)]},
})

# Default blocks for a full single-phase hybrid (used before/without a profile).
DEFAULT_KEYS = [r.key for r in REGISTERS
                if r.group in ("core", "clock", "hybrid", "battery", "pv1", "pv2")]
BLOCKS, BLOCK_NEEDS = make_blocks(DEFAULT_KEYS)

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
REG_TIME_CONFIG = 0x1004      # year(0-99), month, day, hour, minute, second
REG_TIME_CONTROL = 0x100A     # write 1 to apply; read back 0 = success
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


def decode(raw: dict[int, int], family: str = "modern") -> dict:
    """Turn {address: word} into {key: value}. Missing registers -> None."""
    t = table(family)
    data: dict = {}
    for reg in t["registers"]:
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
    fr = t["faults"]
    for idx, addr in enumerate(range(fr[0], fr[1] + 1), start=1):
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
    states = LEGACY_STATES if family == "legacy_storage" else SYS_STATES
    data["sys_state_text"] = states.get(st) if st is not None else None
    m = data.get("energy_storage_mode")
    data["energy_storage_mode_text"] = STORAGE_MODES.get(m) if m is not None else None
    a = data.get("passive_timeout_action")
    data["passive_timeout_action_text"] = TIMEOUT_ACTIONS.get(a) if a is not None else None

    pvs = [data.get(f"pv{i}_power") for i in range(1, 5)]
    pvs = [p for p in pvs if p is not None]
    if data.get("pv_total_power_reg") is not None:
        data["pv_power"] = data["pv_total_power_reg"]
    else:
        data["pv_power"] = sum(pvs) if pvs else None

    g = data.get("grid_power")
    data["grid_export_power"] = None if g is None else max(g, 0)
    data["grid_import_power"] = None if g is None else max(-g, 0)

    # Battery totals: prefer the inverter's own total, else sum the inputs.
    b1, b2 = data.get("battery1_power"), data.get("battery2_power")
    if data.get("battery_total_power_reg") is not None:
        b = data["battery_total_power_reg"]
    elif b1 is None and b2 is None:
        b = None
    else:
        b = (b1 or 0) + (b2 or 0)
    data["battery_power"] = b
    s1, s2 = data.get("battery1_soc"), data.get("battery2_soc")
    if data.get("battery_soc_avg_reg") is not None:
        data["battery_soc"] = data["battery_soc_avg_reg"]
    elif s1 is not None and s2 is not None:
        data["battery_soc"] = round((s1 + s2) / 2)
    else:
        data["battery_soc"] = s1 if s1 is not None else s2
    data["battery_charge_power"] = None if b is None else max(b, 0)
    data["battery_discharge_power"] = None if b is None else max(-b, 0)

    if family == "legacy_storage" and 0x2001 in raw:
        data["serial"] = _ascii([raw.get(a, 0) for a in range(0x2001, 0x2008)])
        sw = [raw.get(a) for a in (0x2008, 0x2009)]
        hw = [raw.get(a) for a in (0x200A, 0x200B)]
        data["sw_version"] = "-".join(f"{w:04X}" for w in sw) if None not in sw else None
        data["hw_version"] = "-".join(f"{w:04X}" for w in hw) if None not in hw else None
    if family == "modern" and 0x0445 in raw:
        data["serial"] = _ascii([raw.get(a, 0) for a in range(0x0445, 0x044C)])
        data["hw_version"] = _ascii([raw.get(a, 0) for a in (0x044D, 0x044E)])
        data["sw_version"] = _sw(raw, 0x044F)
        data["sw_version_master"] = _sw(raw, 0x0453)
    data["battery_action"] = battery_action(data) if family == "modern" else None
    data["inverter_clock"] = clock(data)
    return data


def clock(data: dict):
    """Naive datetime from the inverter clock registers, or None."""
    from datetime import datetime
    parts = [data.get(k) for k in ("clock_year", "clock_month", "clock_day",
                                   "clock_hour", "clock_minute", "clock_second")]
    if any(p is None for p in parts):
        return None
    year = parts[0] + 2000 if parts[0] < 100 else parts[0]
    try:
        return datetime(year, *parts[1:])
    except ValueError:
        return None


def pack_time(dt) -> list[int]:
    return [dt.year % 100, dt.month, dt.day, dt.hour, dt.minute, dt.second]


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


# --------------------------------------------------------------------------- native slots
# Timing mode (energy storage mode 2): 4 slots, ID 0..3, lower ID = higher priority.
REG_TIMING_BLOCK = 0x1111   # ID, on/off bits, chg start, chg end, dis start, dis end,
                            # chg power (U32 W), dis power (U32 W)
REG_TIMING_CONTROL = 0x111F
# Time of use (energy storage mode 1): rules ID 0..3.
REG_TOU_BLOCK = 0x1120      # ID, enable, start, end, target SOC, power (U32 W),
                            # date start (MM<<8|DD), date end, weekday bits (bit0=Mon)
REG_TOU_CONTROL = 0x112F
MODE_TOU = 1
MODE_TIMING = 2

CONTROL_STATUS = {
    0x0000: "success",
    0x0001: "in progress",
    0xFFFB: "inverter refused (busy or configuration failed)",
    0xFFFC: "no response from controller",
    0xFFFD: "function forbidden",
    0xFFFE: "failed to save parameters",
    0xFFFF: "invalid parameters",
}

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def hhmm(t) -> int:
    """datetime.time / 'HH:MM' -> hour<<8 | minute."""
    if isinstance(t, str):
        h, m = (int(x) for x in t.split(":")[:2])
    else:
        h, m = t.hour, t.minute
    return (h << 8) | m


def unpack_hhmm(word: int) -> str:
    return f"{(word >> 8) & 0xFF:02d}:{word & 0xFF:02d}"


def pack_u32(value: int) -> list[int]:
    value = int(value) & 0xFFFFFFFF
    return [value >> 16, value & 0xFFFF]


def pack_timing(slot_id: int, charge_on: bool, discharge_on: bool, charge_start, charge_end,
                discharge_start, discharge_end, charge_power: int, discharge_power: int) -> list[int]:
    flags = (1 if charge_on else 0) | (2 if discharge_on else 0)
    return ([slot_id, flags, hhmm(charge_start), hhmm(charge_end), hhmm(discharge_start),
             hhmm(discharge_end)] + pack_u32(abs(charge_power)) + pack_u32(abs(discharge_power)))


def pack_tou(rule_id: int, enabled: bool, start, end, target_soc: int, power: int,
             weekdays: list[str] | None = None, date_start=(1, 1), date_end=(12, 31)) -> list[int]:
    days = weekdays if weekdays else WEEKDAYS
    bits = sum(1 << WEEKDAYS.index(d) for d in days)
    return ([rule_id, 1 if enabled else 0, hhmm(start), hhmm(end), int(target_soc)]
            + pack_u32(abs(power))
            + [(date_start[0] << 8) | date_start[1], (date_end[0] << 8) | date_end[1], bits])
