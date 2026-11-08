"""Minimal async Modbus client for Sofar inverters behind an IP gateway.

Deliberately dependency-free (no pymodbus) so Home Assistant upgrades can't
break it. Supports two framings:

* ``tcp``         – Modbus TCP (MBAP header). Use when the gateway is in
                    "Modbus TCP <-> RTU" conversion mode (Ebyte NE2-D14E:
                    "Modbus gateway" / "Simple protocol conversion").
* ``rtu_over_tcp`` – raw RTU frames with CRC sent over a TCP socket. Use when
                    the gateway is in transparent / "None" protocol mode.

Function codes: 0x03 (read holding registers), 0x10 (write multiple
registers) and, for older ME3000SP / HYD-ES inverters, Sofar's non-standard
0x42 passive-mode command. Gateways in Modbus TCP conversion mode often drop
0x42; use RTU over TCP (transparent mode) for those inverters.
"""
from __future__ import annotations

import asyncio
import logging
import struct

_LOGGER = logging.getLogger(__name__)

FRAMING_TCP = "tcp"
FRAMING_RTU_OVER_TCP = "rtu_over_tcp"

EXCEPTION_TEXT = {
    1: "illegal function",
    2: "illegal register address",
    3: "illegal register value",
    4: "slave device fault",
    6: "slave device busy",
    7: "slave device busy",
}


class ModbusError(Exception):
    """Transport or protocol error."""


class ModbusExceptionResponse(ModbusError):
    """The inverter answered with a Modbus exception."""

    def __init__(self, function: int, code: int) -> None:
        self.function = function
        self.code = code
        super().__init__(
            f"Modbus exception {code} ({EXCEPTION_TEXT.get(code, 'unknown')}) "
            f"for function 0x{function:02X}"
        )


def crc16(data: bytes) -> int:
    """Modbus RTU CRC16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


class SofarModbusClient:
    """One TCP connection, one request at a time."""

    def __init__(
        self,
        host: str,
        port: int,
        slave: int = 1,
        framing: str = FRAMING_TCP,
        timeout: float = 5.0,
        inter_request_delay: float = 0.05,
    ) -> None:
        self.host = host
        self.port = port
        self.slave = slave
        self.framing = framing
        self.timeout = timeout
        self.inter_request_delay = inter_request_delay
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._tid = 0

    # ------------------------------------------------------------------ connection
    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise ModbusError(f"Cannot connect to {self.host}:{self.port}: {err}") from err
        _LOGGER.debug("Connected to %s:%s (%s)", self.host, self.port, self.framing)

    async def close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ public API
    async def read_holding(self, address: int, count: int) -> list[int]:
        if not 1 <= count <= 125:
            raise ValueError("count must be 1..125")
        pdu = struct.pack(">BHH", 0x03, address, count)
        resp = await self._request(pdu)
        # resp = byte_count + data (function code already stripped)
        if len(resp) != 1 + count * 2 or resp[0] != count * 2:
            raise ModbusError(f"Bad read response length for 0x{address:04X}/{count}")
        return list(struct.unpack(f">{count}H", resp[1:]))

    async def write_registers(self, address: int, values: list[int]) -> None:
        count = len(values)
        if not 1 <= count <= 123:
            raise ValueError("1..123 registers per write")
        pdu = struct.pack(">BHHB", 0x10, address, count, count * 2) + struct.pack(
            f">{count}H", *[v & 0xFFFF for v in values]
        )
        resp = await self._request(pdu)
        if len(resp) != 4:
            raise ModbusError("Bad write response length")
        r_addr, r_count = struct.unpack(">HH", resp)
        if r_addr != address or r_count != count:
            raise ModbusError(
                f"Write echo mismatch: 0x{r_addr:04X}/{r_count} != 0x{address:04X}/{count}"
            )

    async def passive_command(self, register: int, value: int) -> int:
        """Sofar legacy passive command (FC 0x42). Returns the status word."""
        pdu = struct.pack(">BHH", 0x42, register, int(value) & 0xFFFF)
        resp = await self._request(pdu)
        # resp = byte_count + status (function code already stripped)
        if len(resp) < 3:
            raise ModbusError("Bad 0x42 response length")
        return (resp[1] << 8) | resp[2]

    # ------------------------------------------------------------------ internals
    async def _request(self, pdu: bytes) -> bytes:
        """Send a PDU and return the response PDU. One retry on transport errors."""
        async with self._lock:
            last_err: Exception | None = None
            for attempt in (1, 2):
                try:
                    await self._connect()
                    resp = await asyncio.wait_for(self._transact(pdu), self.timeout)
                    if self.inter_request_delay:
                        await asyncio.sleep(self.inter_request_delay)
                    return resp
                except ModbusExceptionResponse:
                    raise
                except (ModbusError, OSError, asyncio.TimeoutError,
                        asyncio.IncompleteReadError) as err:
                    last_err = err
                    _LOGGER.debug("Modbus attempt %s failed: %r", attempt, err)
                    # Drop the socket: clears any half-read / stale bytes.
                    await self.close()
            raise ModbusError(f"Request failed: {last_err!r}")

    async def _transact(self, pdu: bytes) -> bytes:
        assert self._reader is not None and self._writer is not None
        function = pdu[0]
        if self.framing == FRAMING_TCP:
            resp = await self._transact_tcp(pdu)
        else:
            resp = await self._transact_rtu(pdu)
        if resp[0] == function | 0x80:
            raise ModbusExceptionResponse(function, resp[1] if len(resp) > 1 else 0)
        if resp[0] != function:
            raise ModbusError(f"Unexpected function 0x{resp[0]:02X} in response")
        return resp[1:]

    async def _transact_tcp(self, pdu: bytes) -> bytes:
        self._tid = (self._tid + 1) & 0xFFFF
        tid = self._tid
        frame = struct.pack(">HHHB", tid, 0, len(pdu) + 1, self.slave) + pdu
        self._writer.write(frame)
        await self._writer.drain()
        while True:
            header = await self._reader.readexactly(7)
            r_tid, r_pid, length, unit = struct.unpack(">HHHB", header)
            if r_pid != 0 or not 2 <= length <= 260:
                raise ModbusError("Corrupt MBAP header")
            body = await self._reader.readexactly(length - 1)
            if r_tid != tid:
                _LOGGER.debug("Discarding stale response tid=%s (want %s)", r_tid, tid)
                continue
            if unit not in (self.slave, 0, 0xFF):
                raise ModbusError(f"Response from unit {unit}, expected {self.slave}")
            return body

    async def _transact_rtu(self, pdu: bytes) -> bytes:
        adu = bytes([self.slave]) + pdu
        crc = crc16(adu)
        self._writer.write(adu + bytes([crc & 0xFF, crc >> 8]))
        await self._writer.drain()

        head = await self._reader.readexactly(2)
        unit, func = head[0], head[1]
        if func & 0x80:
            rest = await self._reader.readexactly(3)  # code + crc
        elif func in (0x03, 0x42):
            byte_count = await self._reader.readexactly(1)
            rest = byte_count + await self._reader.readexactly(byte_count[0] + 2)
        elif func == 0x10:
            rest = await self._reader.readexactly(6)
        else:
            raise ModbusError(f"Unexpected RTU function 0x{func:02X}")
        frame = head + rest
        if crc16(frame[:-2]) != (frame[-2] | frame[-1] << 8):
            raise ModbusError("RTU CRC mismatch")
        if unit != self.slave:
            raise ModbusError(f"Response from unit {unit}, expected {self.slave}")
        return frame[1:-2]
