# Environmental Sensor Node

A battery-powered node that logs motion and environmental data and reports it
to a host PC over USB.

## Power
- Single 3.3 V rail from an LDO fed by a Li-ion cell.

## Sensors and interfaces
- IMU and barometric pressure sensor on a shared SPI bus, each with its own
  chip select. The IMU also has a data-ready interrupt line.
- Temperature and humidity sensor on I2C.
- USB full-speed device connection to the host.
- Serial debug console (TX and RX only).
- Three analog inputs: battery voltage divider and two thermistors.
- Two dimmable status LEDs (PWM).
- One user button and one enable line for the sensor power switch.

## Constraints
- Firmware is expected to need about 28 KB of flash and 6 KB of RAM.
- MCU budget is $4.00 at most, and we want at least 1,000 in stock.
- The board is small: the MCU footprint must not exceed 10 mm x 10 mm, and
  nothing on the board can be taller than 2 mm.
- Operates outdoors from -20 C to 70 C.
