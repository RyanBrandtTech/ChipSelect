# Dual DC Motor Controller

Controller board for a small two-wheeled robot. Runs from the robot's 5 V
logic supply.

- Two brushed DC motors, each driven through an H-bridge that takes two PWM
  inputs and an enable.
- Each motor has a current-sense output that we need to read.
- Quadrature encoders on both motors (read with plain interrupts, no special
  timer mode needed).
- Talks to the main computer over CAN.
- A UART for a debug terminal would be nice to have.
- Should be cheap. Under two dollars if possible.
