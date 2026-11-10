"""Inverter autodetection (pure Python, no Home Assistant imports).

Works out what this Sofar has from the inverter itself:
1. Protocol family – the modern map answers at 0x0404, the legacy storage map
   (ME3000SP / HYD-ES) at 0x0200.
2. Input channel config (0x1011..0x1020) – the inverter's own list of which DC
   channels are PV strings (1..127) and which are batteries (128..255);
   channels with the same value are paralleled.
3. Address masks – the first 4 registers of each 64-register field say which
   registers in that field are implemented.
4. A probe read of every candidate register.
"""
from __future__ import annotations

import logging

from .modbus import ModbusError, ModbusExceptionResponse, SofarModbusClient
from .registers import (
    INFO_RANGES,
    MASK_FIELDS,
    REG_INPUT_CHANNELS,
    REGISTERS,
    decode,
    reg_addresses,
    runs,
    table,
)

_LOGGER = logging.getLogger(__name__)

FAMILY_MODERN = "modern"
# Bump when registers are added, so existing installs re-detect automatically.
MAP_VERSION = 2
FAMILY_LEGACY_STORAGE = "legacy_storage"


class UnsupportedInverter(Exception):
    """Inverter answers, but on a protocol this version doesn't support yet."""

    def __init__(self, family: str) -> None:
        self.family = family
        super().__init__(family)


async def read_values(client: SofarModbusClient, addresses, chunk: int = 8) -> dict[int, int]:
    """Read addresses in small runs; unreadable registers are simply absent.

    Chunks of 8 suit gateways with small frame buffers. A chunk that fails is
    retried register by register; repeated transport failures abort.
    """
    out: dict[int, int] = {}
    transport_failures = 0
    for start, count in runs(addresses, max_gap=0, max_len=1000):
        for off in range(0, count, chunk):
            s, c = start + off, min(chunk, count - off)
            try:
                for i, w in enumerate(await client.read_holding(s, c)):
                    out[s + i] = w
                transport_failures = 0
                continue
            except ModbusExceptionResponse:
                pass
            except ModbusError:
                transport_failures += 1
                if transport_failures >= 3:
                    raise
            for a in range(s, s + c):
                try:
                    out[a] = (await client.read_holding(a, 1))[0]
                except ModbusExceptionResponse:
                    pass
    return out


def mask_bit(masks: dict[int, int | None], addr: int) -> bool | None:
    """True/False if the field's mask says so, None if no usable mask."""
    field = addr & ~0x3F
    m = masks.get(field)
    if m is None or (m >> 4) == 0:  # only the mask registers themselves flagged: no info
        return None
    return bool((m >> (addr - field)) & 1)


def parse_channels(words: list[int] | None) -> tuple[int | None, int | None]:
    if not words:
        return None, None
    pv = {w for w in words if 1 <= w <= 127}
    bat = {w for w in words if 128 <= w <= 255}
    if not pv and not bat:
        return None, None
    return len(pv), len(bat)


def build_profile(values: dict[int, int], masks: dict[int, int | None],
                  channels: list[int] | None) -> dict:
    """Decide capabilities and the register set from probe results."""
    def readable(r) -> bool:
        return all(a in values for a in range(r.address, r.address + r.size))

    # Phases: a live L2 voltage beats the mask (Sofar's masks flag L2/L3 on
    # single-phase models too).
    if 0x0498 in values:
        phases = 3 if values[0x0498] > 500 else 1  # > 50 V on L2
    else:
        phases = 3 if mask_bit(masks, 0x0498) else 1

    # PV inputs and batteries: the inverter's channel config is authoritative.
    pv_inputs, battery_inputs = parse_channels(channels)
    if pv_inputs is None:
        live = [values.get(a, 0) > 300 for a in (0x0584, 0x0587, 0x058A, 0x058D)]  # > 30 V
        mask_pv = [mask_bit(masks, a) for a in (0x0584, 0x0587, 0x058A, 0x058D)]
        if any(live):  # daytime: highest string with voltage
            pv_inputs = max(i + 1 for i, on in enumerate(live) if on)
            pv_inputs = max(pv_inputs, 2 if 0x0587 in values else 1)
        elif any(m is not None for m in mask_pv):
            pv_inputs = sum(1 for m in mask_pv if m)
        else:
            pv_inputs = 2
    if battery_inputs is None:
        v1, v2 = values.get(0x0604, 0), values.get(0x060B, 0)
        if v1 > 0 or v2 > 0:
            battery_inputs = int(v1 > 0) + int(v2 > 0)
        elif 0x1110 in values:
            battery_inputs = 1  # storage-mode register present: it's a hybrid
        else:
            battery_inputs = 1 if mask_bit(masks, 0x0604) else 0
    readable_pv = sum(1 for a in (0x0584, 0x0587, 0x058A, 0x058D) if a in values)
    pv_inputs = max(0, min(4, pv_inputs, readable_pv))
    battery_inputs = max(0, min(2, battery_inputs))
    hybrid = battery_inputs > 0

    keys = []
    for r in REGISTERS:
        if not readable(r):
            continue
        g = r.group
        if g in ("core", "clock"):
            ok = True
        elif g == "grid3":
            ok = phases == 3
        elif g == "eps3":
            ok = phases == 3 and hybrid
        elif g.startswith("pv") and g[2:].isdigit():
            ok = int(g[2:]) <= pv_inputs
        elif g in ("battery", "hybrid", "batconfig"):
            ok = hybrid
        elif g == "battery2":
            ok = battery_inputs >= 2
        elif g in ("pvtotal", "battery_total", "optional"):
            ok = mask_bit(masks, r.address) is True
        elif g == "internal":
            ok = mask_bit(masks, r.address) is not False
        else:
            ok = False
        if ok:
            keys.append(r.key)

    kind = "Hybrid" if hybrid else "PV"
    model = f"{kind} inverter, {phases}-phase, {pv_inputs} PV input{'s' if pv_inputs != 1 else ''}"
    if hybrid:
        model += f", {battery_inputs} battery input{'s' if battery_inputs != 1 else ''}"
    return {
        "family": FAMILY_MODERN,
        "phases": phases,
        "pv_inputs": pv_inputs,
        "battery_inputs": battery_inputs,
        "hybrid": hybrid,
        "model": model,
        "registers": keys,
        "map_version": MAP_VERSION,
        "masks": {f"0x{k:04X}": (f"0x{v:016X}" if v is not None else None) for k, v in masks.items()},
        "channels": channels,
    }


def build_profile_legacy(values: dict[int, int]) -> dict:
    """ME3000SP / HYD-ES: single phase, one battery; PV only on the HYD-ES."""
    t = table(FAMILY_LEGACY_STORAGE)
    keys = [r.key for r in t["registers"]
            if all(a in values for a in range(r.address, r.address + r.size))]
    pv_inputs = sum(1 for k in ("pv1_voltage", "pv2_voltage") if k in keys)
    if pv_inputs:
        model = f"HYD-ES type hybrid (legacy protocol), {pv_inputs} PV input{'s' if pv_inputs != 1 else ''}"
    else:
        model = "ME3000SP type AC storage (legacy protocol)"
    return {
        "family": FAMILY_LEGACY_STORAGE,
        "phases": 1,
        "pv_inputs": pv_inputs,
        "battery_inputs": 1,
        "hybrid": True,
        "model": model,
        "registers": keys,
        "map_version": MAP_VERSION,
        "masks": {},
        "channels": None,
    }


async def detect(client: SofarModbusClient) -> dict:
    """Probe the inverter and return a profile dict (JSON-serialisable)."""
    try:
        await client.read_holding(0x0404, 1)
    except ModbusError as err:
        try:
            await client.read_holding(0x0200, 1)
        except ModbusError:
            raise err from None
        return await _detect_legacy(client)

    masks: dict[int, int | None] = {}
    for field in MASK_FIELDS:
        try:
            w = await client.read_holding(field, 4)
            masks[field] = (w[0] << 48) | (w[1] << 32) | (w[2] << 16) | w[3]
        except ModbusError:
            masks[field] = None

    try:
        channels = (await client.read_holding(REG_INPUT_CHANNELS, 8)
                    + await client.read_holding(REG_INPUT_CHANNELS + 8, 8))
    except ModbusError:
        channels = None

    candidates = reg_addresses([r.key for r in REGISTERS])
    for s, c in INFO_RANGES:
        candidates.update(range(s, s + c))
    values = await read_values(client, candidates)

    profile = build_profile(values, masks, channels)
    info = decode(values)
    profile["serial"] = info.get("serial") or None
    profile["sw_version"] = info.get("sw_version")
    _LOGGER.info("Sofar detected: %s (%d registers)", profile["model"], len(profile["registers"]))
    return profile


async def _detect_legacy(client: SofarModbusClient) -> dict:
    t = table(FAMILY_LEGACY_STORAGE)
    candidates = reg_addresses([r.key for r in t["registers"]], FAMILY_LEGACY_STORAGE)
    for s0, c0 in t["info"]:
        candidates.update(range(s0, s0 + c0))
    values = await read_values(client, candidates)
    profile = build_profile_legacy(values)
    info = decode(values, FAMILY_LEGACY_STORAGE)
    profile["serial"] = info.get("serial") or None
    profile["sw_version"] = info.get("sw_version")
    _LOGGER.info("Sofar detected (legacy): %s (%d registers)", profile["model"], len(profile["registers"]))
    return profile
