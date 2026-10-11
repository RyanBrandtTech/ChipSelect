"""Signal naming shared by the Parts Database and the Formal Specification."""

# Canonical signal names for the bus types whose signals are standardised.
# Parts must use these names so that a specification can ask for them on any
# part. ethernet, ext_flash and other peripherals keep their datasheet names.
BUS_SIGNALS = {
    "spi": ("SCK", "MISO", "MOSI", "NSS"),
    "i2c": ("SCL", "SDA"),
    "uart": ("TX", "RX", "RTS", "CTS", "CK"),
    "can": ("TX", "RX"),
    "usb": ("DM", "DP", "ID", "VBUS"),
}

# Peripheral types requested as a number of channels rather than named signals.
CHANNEL_TYPES = ("adc", "dac", "pwm")
