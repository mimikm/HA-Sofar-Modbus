"""Diagnostics download: detected profile, poll state and a full register dump.

The register dump is what's needed to add support for a new Sofar model.
"""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST

from .coordinator import scan_registers
from .registers import SCAN_RANGES

TO_REDACT = {CONF_HOST, "serial", "unique_id"}


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    c = entry.runtime_data
    try:
        dump = await scan_registers(c.client, SCAN_RANGES)
    except Exception as err:  # noqa: BLE001
        dump = {"error": str(err)}
    return {
        "entry": async_redact_data({**entry.data, "profile": None}, TO_REDACT),
        "options": dict(entry.options),
        "profile": async_redact_data(c.profile, TO_REDACT),
        "polling": {
            "blocks": [f"0x{b[1]:04X}+{b[2]}" for b in c.blocks],
            "small_read_blocks": sorted(c.small_blocks),
            "failed_blocks": c.failed_blocks,
            "last_errors": c.last_errors,
        },
        "data": async_redact_data(_clean(c.data or {}), TO_REDACT),
        "slots": c.slots,
        "register_dump": dump,
    }
