"""Polling coordinator + write helpers."""
from __future__ import annotations

from datetime import timedelta
import time
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTO_TIME_SYNC,
    CONF_KEEPALIVE,
    DEFAULT_AUTO_TIME_SYNC,
    TIME_SYNC_THRESHOLD,
    CONF_MAX_BATTERY_POWER,
    CONF_SCAN_INTERVAL,
    DEFAULT_KEEPALIVE,
    DEFAULT_MAX_BATTERY_POWER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .modbus import ModbusError, ModbusExceptionResponse, SofarModbusClient
from .registers import (
    BLOCKS,
    MODE_PASSIVE,
    REG_PASSIVE_BLOCK,
    REG_PASSIVE_TIMEOUT,
    REG_REMOTE_ON_OFF,
    REG_STORAGE_MODE,
    REG_TIME_CONFIG,
    REG_TIME_CONTROL,
    SCAN_RANGES,
    action_to_passive,
    decode,
    known_runs,
    ACTION_AUTO,
    ACTION_NO_DISCHARGE,
    MODE_TIMING,
    MODE_TOU,
    REG_TIMING_BLOCK,
    REG_TIMING_CONTROL,
    REG_TOU_BLOCK,
    REG_TOU_CONTROL,
    pack_passive,
    pack_time,
    pack_timing,
    pack_tou,
)
from .schedule import active_slot, is_expired, make_slot, target


def _naive(value):
    """Datetimes from services may carry a tz: convert to local naive."""
    from datetime import datetime
    if isinstance(value, datetime) and value.tzinfo is not None:
        return dt_util.as_local(value).replace(tzinfo=None)
    return value

_LOGGER = logging.getLogger(__name__)


MAX_FALLBACK_CHUNK = 8


def _chunks(runs: list[tuple[int, int]], size: int) -> list[tuple[int, int]]:
    out = []
    for run_start, run_count in runs:
        for off in range(0, run_count, size):
            out.append((run_start + off, min(size, run_count - off)))
    return out


async def read_blocks(
    client: SofarModbusClient, blocks, small: set[str] | None = None
) -> tuple[dict[int, int], list[str], dict[str, str]]:
    """Read register blocks, tolerating failures.

    If a block read fails for any reason (exception reply, timeout, gateway
    hiccup on larger frames), fall back to reading only the documented
    registers in chunks of <= 8. Blocks that needed the fallback are added to
    ``small`` so later polls go straight to chunked reads.
    Returns (raw, failed_block_names, {block: error_text}).
    """
    small = small if small is not None else set()
    raw: dict[int, int] = {}
    failed: list[str] = []
    errors: dict[str, str] = {}
    transport_failures = 0
    for idx, (name, start, count, _poll) in enumerate(blocks):
        if transport_failures >= 3:
            failed.extend(b[0] for b in blocks[idx:])
            break
        if name not in small:
            try:
                for i, w in enumerate(await client.read_holding(start, count)):
                    raw[start + i] = w
                transport_failures = 0
                continue
            except ModbusError as err:
                errors[name] = str(err)
                _LOGGER.debug("Block %s (0x%04X/%d) failed: %s; trying small reads",
                              name, start, count, err)
        got_any = False
        for c_start, c_count in _chunks(known_runs(start, count), MAX_FALLBACK_CHUNK):
            if transport_failures >= 3:
                break
            try:
                for i, w in enumerate(await client.read_holding(c_start, c_count)):
                    raw[c_start + i] = w
                got_any = True
                transport_failures = 0
            except ModbusExceptionResponse as err:
                errors.setdefault(name, str(err))
            except ModbusError as err:
                errors.setdefault(name, str(err))
                transport_failures += 1
        if got_any:
            if name not in small:
                _LOGGER.info("Sofar: block %s only readable in small chunks", name)
            small.add(name)
        else:
            failed.append(name)
    return raw, failed, errors


class SofarCoordinator(DataUpdateCoordinator[dict]):
    """Polls the inverter and owns the Modbus client."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: SofarModbusClient) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.info: dict[int, int] = {}
        self.failed_blocks: list[str] = []
        self.small_blocks: set[str] = set()
        self.last_errors: dict[str, str] = {}
        self.action_power: int = int(self.max_battery_power)
        self._last_passive: tuple[int, int, int] | None = None
        self._last_auto_sync: float = 0.0
        # Native slot 1 settings shown as entities (restored by the entities).
        self.native: dict = {
            "timing_charge_enabled": False, "timing_discharge_enabled": False,
            "timing_charge_start": "02:00", "timing_charge_end": "05:00",
            "timing_discharge_start": "16:00", "timing_discharge_end": "19:00",
            "timing_charge_power": DEFAULT_MAX_BATTERY_POWER,
            "timing_discharge_power": DEFAULT_MAX_BATTERY_POWER,
            "tou_enabled": True, "tou_start": "00:30", "tou_end": "04:30",
            "tou_target_soc": 100, "tou_power": DEFAULT_MAX_BATTERY_POWER,
        }
        # Home Assistant-driven slots.
        self.slots: list[dict] = []
        self.slot_store = None          # helpers.storage.Store, set in __init__.py
        self.slot_status: str = "idle"
        self._slot_applied: tuple[str, int] | None = None
        self._slot_latched: set[str] = set()

    # ------------------------------------------------------------------ options
    @property
    def max_battery_power(self) -> int:
        return int(self.config_entry.options.get(CONF_MAX_BATTERY_POWER, DEFAULT_MAX_BATTERY_POWER))

    @property
    def auto_time_sync(self) -> bool:
        return bool(self.config_entry.options.get(CONF_AUTO_TIME_SYNC, DEFAULT_AUTO_TIME_SYNC))

    @property
    def keepalive(self) -> bool:
        return bool(self.config_entry.options.get(CONF_KEEPALIVE, DEFAULT_KEEPALIVE))

    # ------------------------------------------------------------------ polling
    async def _async_update_data(self) -> dict:
        if not self.info:
            info_blocks = [b for b in BLOCKS if not b[3]]
            info, _, _ = await read_blocks(self.client, info_blocks, self.small_blocks)
            self.info = info

        poll_blocks = [b for b in BLOCKS if b[3]]
        raw, failed, errors = await read_blocks(self.client, poll_blocks, self.small_blocks)
        self.last_errors = errors
        if not raw:
            first = next(iter(errors.values()), "no reply")
            raise UpdateFailed(f"No response from inverter: {first}")
        if failed != self.failed_blocks:
            if failed:
                _LOGGER.warning(
                    "Sofar: register blocks not readable: %s",
                    "; ".join(f"{n} ({errors.get(n, '?')})" for n in failed),
                )
            self.failed_blocks = failed

        raw.update(self.info)
        data = decode(raw)

        # Inverter clock: the inverter keeps local wall-clock time.
        inv = data.get("inverter_clock")
        data["clock_drift"] = None
        if inv is not None:
            now = dt_util.now().replace(tzinfo=None, microsecond=0)
            data["clock_drift"] = int((inv - now).total_seconds())
            data["inverter_clock"] = inv.replace(tzinfo=dt_util.get_default_time_zone())
            if (
                self.auto_time_sync
                and abs(data["clock_drift"]) > TIME_SYNC_THRESHOLD
                and time.monotonic() - self._last_auto_sync > 3600
            ):
                self._last_auto_sync = time.monotonic()
                try:
                    await self._write_time()
                    _LOGGER.info("Sofar clock was %ss off, synced", data["clock_drift"])
                except ModbusError as err:
                    _LOGGER.warning("Sofar clock auto-sync failed: %s", err)

        await self._run_slots(data)

        if (
            self.keepalive
            and self._last_passive is not None
            and data.get("energy_storage_mode") == MODE_PASSIVE
        ):
            try:
                await self.client.write_registers(REG_PASSIVE_BLOCK, pack_passive(*self._last_passive))
            except ModbusError as err:
                _LOGGER.warning("Passive keep-alive write failed: %s", err)
        return data

    # ------------------------------------------------------------------ writes
    async def _write(self, address: int, values: list[int]) -> None:
        try:
            await self.client.write_registers(address, values)
        except ModbusError as err:
            raise HomeAssistantError(f"Write to 0x{address:04X} failed: {err}") from err

    async def async_set_storage_mode(self, mode: int) -> None:
        await self._write(REG_STORAGE_MODE, [mode])
        if mode != MODE_PASSIVE:
            self._last_passive = None
        await self.async_request_refresh()

    async def async_set_passive(self, grid: int, bmin: int, bmax: int, ensure_mode: bool = True) -> None:
        """Write all three passive values in one FC16 frame, then enter passive mode."""
        if bmin > bmax:
            raise HomeAssistantError("battery_min must be <= battery_max")
        await self._write(REG_PASSIVE_BLOCK, pack_passive(grid, bmin, bmax))
        self._last_passive = (int(grid), int(bmin), int(bmax))
        if ensure_mode and (self.data or {}).get("energy_storage_mode") != MODE_PASSIVE:
            await self._write(REG_STORAGE_MODE, [MODE_PASSIVE])
        await self.async_request_refresh()

    async def async_set_passive_value(self, key: str, value: int) -> None:
        d = self.data or {}
        current = {
            "passive_grid_power": d.get("passive_grid_power") or 0,
            "passive_battery_min": d.get("passive_battery_min") or 0,
            "passive_battery_max": d.get("passive_battery_max") or 0,
        }
        current[key] = int(value)
        g, lo, hi = current["passive_grid_power"], current["passive_battery_min"], current["passive_battery_max"]
        if lo > hi:  # keep the pair consistent instead of failing
            if key == "passive_battery_min":
                hi = lo
            else:
                lo = hi
        await self.async_set_passive(g, lo, hi, ensure_mode=False)

    async def async_battery_action(self, action: str, power: int | None = None) -> None:
        power = self.action_power if power is None else int(power)
        power = max(0, min(power, self.max_battery_power))
        values = action_to_passive(action, power, self.max_battery_power)
        if values is None:
            await self.async_set_storage_mode(0)
        else:
            await self.async_set_passive(*values)

    async def async_set_passive_timeout(self, seconds: int | None = None, action: int | None = None) -> None:
        d = self.data or {}
        sec = int(seconds if seconds is not None else d.get("passive_timeout") or 0)
        act = int(action if action is not None else d.get("passive_timeout_action") or 0)
        await self._write(REG_PASSIVE_TIMEOUT, [sec, act])
        await self.async_request_refresh()

    async def _write_time(self) -> None:
        now = dt_util.now()
        await self.client.write_registers(REG_TIME_CONFIG, pack_time(now))
        await self.client.write_registers(REG_TIME_CONTROL, [1])

    async def async_sync_time(self) -> None:
        try:
            await self._write_time()
        except ModbusError as err:
            raise HomeAssistantError(f"Clock sync failed: {err}") from err
        await self.async_request_refresh()

    async def async_set_remote_on(self, on: bool) -> None:
        await self._write(REG_REMOTE_ON_OFF, [1 if on else 0])
        await self.async_request_refresh()

    # ------------------------------------------------------------------ native slots
    async def async_apply_timing(self, slot: int, *, charge_enabled: bool, discharge_enabled: bool,
                                 charge_start, charge_end, discharge_start, discharge_end,
                                 charge_power: int, discharge_power: int, activate: bool = True) -> None:
        values = pack_timing(slot - 1, charge_enabled, discharge_enabled, charge_start, charge_end,
                             discharge_start, discharge_end,
                             min(charge_power, self.max_battery_power),
                             min(discharge_power, self.max_battery_power))
        await self._apply_native(REG_TIMING_BLOCK, values, REG_TIMING_CONTROL,
                                 MODE_TIMING if activate else None, f"Timing slot {slot}")

    async def async_apply_tou(self, rule: int, *, enabled: bool, start, end, target_soc: int,
                              power: int, weekdays: list[str] | None = None,
                              activate: bool = True) -> None:
        values = pack_tou(rule - 1, enabled, start, end, target_soc,
                          min(power, self.max_battery_power), weekdays)
        await self._apply_native(REG_TOU_BLOCK, values, REG_TOU_CONTROL,
                                 MODE_TOU if activate else None, f"Time of use rule {rule}")

    async def async_apply_native_slot1(self, kind: str) -> None:
        n = self.native
        if kind == "timing":
            await self.async_apply_timing(
                1, charge_enabled=n["timing_charge_enabled"], discharge_enabled=n["timing_discharge_enabled"],
                charge_start=n["timing_charge_start"], charge_end=n["timing_charge_end"],
                discharge_start=n["timing_discharge_start"], discharge_end=n["timing_discharge_end"],
                charge_power=n["timing_charge_power"], discharge_power=n["timing_discharge_power"])
        else:
            await self.async_apply_tou(
                1, enabled=n["tou_enabled"], start=n["tou_start"], end=n["tou_end"],
                target_soc=n["tou_target_soc"], power=n["tou_power"])

    async def _apply_native(self, block: int, values: list[int], control: int,
                            mode: int | None, label: str) -> None:
        if self.slots and mode is not None:
            raise HomeAssistantError(
                "Clear the Home Assistant slots first – they would override the inverter mode")
        try:
            readback = await write_native_block(self.client, block, values, control)
        except ModbusError as err:
            raise HomeAssistantError(f"{label}: {err}") from err
        if readback is not None and readback != values[1:]:
            _LOGGER.warning("%s read-back differs: wrote %s, inverter has %s",
                            label, values[1:], readback)
            raise HomeAssistantError(f"{label}: inverter stored different values – check the log")
        _LOGGER.info("%s written%s", label, " and verified" if readback is not None else "")
        if mode is not None:
            await self._write(REG_STORAGE_MODE, [mode])
        await self.async_request_refresh()

    # ------------------------------------------------------------------ HA slots
    async def async_add_slot(self, action: str, start, end, power: int | None,
                             soc: int | None, daily: bool) -> dict:
        now = dt_util.now().replace(tzinfo=None)
        p = self.action_power if power is None else int(power)
        p = max(0, min(p, self.max_battery_power))
        try:
            slot = make_slot(action, _naive(start), _naive(end), p, soc, daily, now)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        self.slots.append(slot)
        await self._save_slots()
        await self.async_request_refresh()
        return slot

    async def async_clear_slots(self, slot_id: str | None = None) -> None:
        before = len(self.slots)
        self.slots = [s for s in self.slots if slot_id is not None and s["id"] != slot_id]
        if slot_id is not None and len(self.slots) == before:
            raise HomeAssistantError(f"No slot with id {slot_id}")
        await self._save_slots()
        await self.async_request_refresh()

    async def _save_slots(self) -> None:
        if self.slot_store is not None:
            await self.slot_store.async_save(
                {"slots": self.slots, "applied": self._slot_applied is not None})

    async def _run_slots(self, data: dict) -> None:
        now = dt_util.now().replace(tzinfo=None)
        expired = [s for s in self.slots if is_expired(s, now)]
        if expired:
            self.slots = [s for s in self.slots if s not in expired]
            self._slot_latched -= {s["id"] for s in expired}
            await self._save_slots()

        slot = active_slot(self.slots, now)
        if slot is None:
            self._slot_latched.clear()
            self.slot_status = "idle"
            if self._slot_applied is not None and await self._apply_action(ACTION_AUTO, 0):
                self._slot_applied = None
                await self._save_slots()
            return

        action, power = target(slot, data.get("battery_soc"))
        if action == ACTION_NO_DISCHARGE:
            self._slot_latched.add(slot["id"])
        elif slot["id"] in self._slot_latched:  # SOC limit reached earlier: stay held
            action, power = ACTION_NO_DISCHARGE, 0
        self.slot_status = f"{slot['action']} ({slot['id']})" + (
            " – SOC limit reached, holding" if action == ACTION_NO_DISCHARGE else "")
        if self._slot_applied != (action, power):
            first = self._slot_applied is None
            if await self._apply_action(action, power):
                self._slot_applied = (action, power)
                if first:
                    await self._save_slots()

    async def _apply_action(self, action: str, power: int) -> bool:
        """Write a battery action without triggering a refresh (used inside polling)."""
        try:
            values = action_to_passive(action, power, self.max_battery_power)
            if values is None:
                await self.client.write_registers(REG_STORAGE_MODE, [0])
                self._last_passive = None
            else:
                await self.client.write_registers(REG_PASSIVE_BLOCK, pack_passive(*values))
                self._last_passive = values
                await self.client.write_registers(REG_STORAGE_MODE, [MODE_PASSIVE])
            _LOGGER.info("Slot scheduler: %s %s W", action, power)
            return True
        except ModbusError as err:
            _LOGGER.warning("Slot scheduler write failed (will retry): %s", err)
            return False

    # ------------------------------------------------------------------ scan
    async def async_scan(self, ranges: list[tuple[int, int]] | None = None) -> dict[str, int | str]:
        """Read every register in the given ranges; unreadable ones are reported."""
        return await scan_registers(self.client, ranges or SCAN_RANGES)


async def scan_registers(client: SofarModbusClient, ranges) -> dict[str, int | str]:
    result: dict[str, int | str] = {}
    for start, end in ranges:
        addr = start
        while addr <= end:
            count = min(16, end - addr + 1)
            try:
                words = await client.read_holding(addr, count)
                for i, w in enumerate(words):
                    result[f"0x{addr + i:04X}"] = w
            except ModbusExceptionResponse:
                # Chunk contains a hole – fall back to single registers.
                for a in range(addr, addr + count):
                    try:
                        result[f"0x{a:04X}"] = (await client.read_holding(a, 1))[0]
                    except ModbusExceptionResponse as err:
                        result[f"0x{a:04X}"] = f"ERR{err.code}"
            addr += count
    return result


async def write_native_block(client: SofarModbusClient, block: int, values: list[int],
                             control: int) -> list[int] | None:
    """Write a Timing/TOU rule in one frame, commit it and check the status.

    Sofar only accepts these when written together, so first try one FC16
    frame covering the rule *and* its control register (reserved registers in
    between written as 0). If the inverter rejects that frame, fall back to
    rule block + separate commit. Returns the read-back rule (registers after
    the ID) or None if read-back isn't supported.
    """
    import asyncio

    from .registers import CONTROL_STATUS

    gap = control - (block + len(values))
    try:
        await client.write_registers(block, values + [0] * gap + [1])
    except ModbusExceptionResponse:
        await client.write_registers(block, values)
        await client.write_registers(control, [1])

    status = 0x0001
    for _ in range(10):
        try:
            status = (await client.read_holding(control, 1))[0]
        except ModbusExceptionResponse:
            status = 0  # control register not readable on this firmware: assume ok
            break
        if status != 0x0001:
            break
        await asyncio.sleep(0.5)
    if status not in (0x0000, 0x0001):
        raise ModbusError(f"Inverter rejected the rule: {CONTROL_STATUS.get(status, hex(status))}")

    # Read back: select the rule ID, then read its fields.
    try:
        await client.write_registers(block, [values[0]])
        return await client.read_holding(block + 1, len(values) - 1)
    except ModbusError as err:
        _LOGGER.debug("Rule read-back not available: %s", err)
        return None
