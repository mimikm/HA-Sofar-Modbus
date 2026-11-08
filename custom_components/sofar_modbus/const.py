"""Constants for the Sofar Modbus integration."""
DOMAIN = "sofar_modbus"
MANUFACTURER = "Sofar Solar"

CONF_SLAVE = "slave"
CONF_FRAMING = "framing"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_BATTERY_POWER = "max_battery_power"
CONF_KEEPALIVE = "passive_keepalive"
CONF_AUTO_TIME_SYNC = "auto_time_sync"

DEFAULT_PORT = 502
DEFAULT_SLAVE = 1
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_MAX_BATTERY_POWER = 3000
DEFAULT_KEEPALIVE = False
DEFAULT_AUTO_TIME_SYNC = False
TIME_SYNC_THRESHOLD = 30  # seconds of drift before auto sync

PLATFORMS = ["sensor", "binary_sensor", "select", "number", "switch", "button", "time"]
