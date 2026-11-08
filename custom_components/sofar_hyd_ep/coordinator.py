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
    pack_passive,
    pack_time,
)

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
