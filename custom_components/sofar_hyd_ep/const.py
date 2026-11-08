"""Constants for the Sofar HYD-EP Modbus integration."""
DOMAIN = "sofar_hyd_ep"
MANUFACTURER = "Sofar Solar"

CONF_SLAVE = "slave"
CONF_FRAMING = "framing"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_BATTERY_POWER = "max_battery_power"
CONF_KEEPALIVE = "passive_keepalive"

DEFAULT_PORT = 502
DEFAULT_SLAVE = 1
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_MAX_BATTERY_POWER = 3000
DEFAULT_KEEPALIVE = False

PLATFORMS = ["sensor", "binary_sensor", "select", "number", "switch"]
