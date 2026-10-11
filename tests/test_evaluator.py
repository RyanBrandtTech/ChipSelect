import copy
import unittest
from pathlib import Path

from chipselect.evaluator import assign_pins, evaluate, evaluate_part
from chipselect.parts_db import load_parts, signal_options
from chipselect.spec import load_spec

ROOT = Path(__file__).resolve().parent.parent


class EvaluatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = load_parts(ROOT / "parts")
        cls.f103 = cls.parts["STM32F103C8T6"]
        cls.spec = load_spec(ROOT / "tests" / "data" / "sensor_node_spec.yaml")

    def spec_with(self, **changes):
        spec = copy.deepcopy(self.spec)
        spec.update(changes)
        return spec

    def assert_valid_assignment(self, part, spec, assignment):
        used = []
        for interface in spec["interfaces"]:
            entry = assignment[interface["name"]]
            if "signals" in interface:
                peripheral = part["peripherals"][entry["peripheral"]]
                self.assertEqual(peripheral["type"], interface["type"])
                self.assertEqual(set(entry["pins"]), set(interface["signals"]))
                self.assertTrue(any(
                    all(pin in option[signal] for signal, pin in entry["pins"].items())
                    for option in signal_options(peripheral)
                ), "pins are not all from one pin option")
                used += entry["pins"].values()
            else:
                self.assertEqual(len(entry["channels"]), interface["channels"])
                signals = [channel["signal"] for channel in entry["channels"]]
                self.assertEqual(len(signals), len(set(signals)))
                for channel in entry["channels"]:
                    name, signal = channel["signal"].split(".")
                    self.assertEqual(part["peripherals"][name]["type"], interface["type"])
                    self.assertTrue(any(
                        channel["pin"] in option[signal]
                        for option in signal_options(part["peripherals"][name])
                    ))
                    used.append(channel["pin"])
        buses = [assignment[i["name"]]["peripheral"] for i in spec["interfaces"] if "signals" in i]
        self.assertEqual(len(buses), len(set(buses)))
        self.assertEqual(len(assignment["gpio"]), spec["gpio"])
        for pin in assignment["gpio"]:
            self.assertIn(pin, part["pins"]["gpio"])
        used += assignment["gpio"]
        self.assertEqual(len(used), len(set(used)), "a pin is used twice")

    def test_example_fits(self):
        assignment, problems = evaluate_part(self.f103, self.spec)
        self.assertEqual(problems, [])
        self.assert_valid_assignment(self.f103, self.spec, assignment)

    def test_recommended_entry_has_price_and_availability(self):
        recommended, rejected = evaluate(self.spec, {"STM32F103C8T6": self.f103})
        self.assertEqual(rejected, {})
        entry = recommended[0]
        self.assertEqual(entry["unit_cost_usd"], self.f103["unit_cost_usd"])
        self.assertEqual(entry["quantity_available"], self.f103["quantity_available"])
        self.assertEqual(entry["spare_gpio"], 37 - 7 - 9 - 5 - 6)  # 7 special pins held back
        self.assertEqual(entry["special_pins_used"], {})

    def test_scalar_limits_reject(self):
        spec = self.spec_with(limits={"max_unit_cost_usd": 1.0, "min_flash_kb": 128})
        _, problems = evaluate_part(self.f103, spec)
        self.assertEqual(len(problems), 2)

    def test_unsupported_supply_and_io_voltage_reject(self):
        spec = self.spec_with(power={"supply_rails_v": [5.0], "io_voltage_v": 1.8})
        _, problems = evaluate_part(self.f103, spec)
        self.assertEqual(len(problems), 3)  # VDD, VDDA, I/O level; VBAT is optional

    def test_pin_contention_rejects_despite_sufficient_counts(self):
        # The part has 3 UARTs and 2 I2C buses, but USART3 and I2C2 exist only
        # on PB10/PB11, so all five cannot be used together.
        interfaces = [
            {"name": f"uart{n}", "type": "uart", "signals": ["TX", "RX"]} for n in range(3)
        ] + [
            {"name": f"i2c{n}", "type": "i2c", "signals": ["SCL", "SDA"]} for n in range(2)
        ]
        assignment, reason = assign_pins(self.f103, self.spec_with(interfaces=interfaces, gpio=0))
        self.assertIsNone(assignment)
        self.assertIn("distinct pins", reason)

    def test_pwm_channels_limited_by_shared_pins(self):
        # Three UARTs and I2C1 take PA2, PA3, PB10, PB11 and four of
        # PA9, PA10, PB6-PB9, which leaves exactly 10 of the 16 PWM channels.
        def spec(channels):
            return self.spec_with(
                interfaces=[
                    {"name": "console", "type": "uart", "signals": ["TX", "RX"]},
                    {"name": "aux", "type": "uart", "signals": ["TX", "RX"]},
                    {"name": "radio", "type": "uart", "signals": ["TX", "RX"]},
                    {"name": "sensors", "type": "i2c", "signals": ["SCL", "SDA"]},
                    {"name": "motors", "type": "pwm", "channels": channels},
                ],
                gpio=0,
            )

        assignment, reason = assign_pins(self.f103, spec(10))
        self.assertIsNone(reason)
        self.assert_valid_assignment(self.f103, spec(10), assignment)
        assignment, reason = assign_pins(self.f103, spec(11))
        self.assertIsNone(assignment)

    def test_default_pins_used_when_uncontended(self):
        assignment, _ = evaluate_part(self.f103, self.spec)
        self.assertEqual(assignment["imu"]["pins"], {"SCK": "PA5", "MISO": "PA6", "MOSI": "PA7"})
        self.assertEqual(assignment["env_sensor"]["pins"], {"SCL": "PB6", "SDA": "PB7"})
        self.assertEqual(assignment["debug_console"]["pins"], {"TX": "PA9", "RX": "PA10"})

    def test_gpio_exhaustion_rejects(self):
        _, problems = evaluate_part(self.f103, self.spec_with(gpio=37 - 14 + 1))
        self.assertEqual(len(problems), 1)
        assignment, problems = evaluate_part(self.f103, self.spec_with(gpio=37 - 14))
        self.assertEqual(problems, [])
        self.assert_valid_assignment(self.f103, self.spec_with(gpio=37 - 14), assignment)

    def test_special_pins_are_last_resort(self):
        special = set(self.f103["pins"]["special"])
        assignment, _ = evaluate_part(self.f103, self.spec_with(gpio=37 - 7 - 14))
        self.assertFalse(special & set(assignment["gpio"]))
        recommended, _ = evaluate(self.spec_with(gpio=37 - 7 - 14 + 1), {"STM32F103C8T6": self.f103})
        self.assertEqual(len(recommended[0]["special_pins_used"]), 1)
        self.assertEqual(recommended[0]["spare_gpio"], 0)

    def test_pin_options_move_as_a_group(self):
        def part(blocker_pins):
            return {
                "pins": {"gpio": ["P1", "P2", "P3", "P4"]},
                "peripherals": {
                    "BUS": {"type": "i2c", "pin_options": [
                        {"SCL": ["P1"], "SDA": ["P2"]},
                        {"SCL": ["P3"], "SDA": ["P4"]},
                    ]},
                    "ADC": {"type": "adc", "signals": {f"IN{n}": [pin] for n, pin in enumerate(blocker_pins)}},
                },
            }

        def spec(channels):
            return {
                "interfaces": [
                    {"name": "bus", "type": "i2c", "signals": ["SCL", "SDA"]},
                    {"name": "sense", "type": "adc", "channels": channels},
                ],
                "gpio": 0,
            }

        # ADC on P2 forces the bus onto its second option as a whole.
        assignment, _ = assign_pins(part(["P2"]), spec(1))
        self.assertEqual(assignment["bus"]["pins"], {"SCL": "P3", "SDA": "P4"})
        # ADC on P2 and P3 blocks both options, though P1 and P4 are free.
        assignment, _ = assign_pins(part(["P2", "P3"]), spec(2))
        self.assertIsNone(assignment)

    def test_database_against_example(self):
        recommended, rejected = evaluate(self.spec, self.parts)
        numbers = [entry["part_number"] for entry in recommended]
        self.assertEqual(numbers, sorted(numbers))
        self.assertTrue({"STM32F103C8T6", "STM32F103CBT6"} <= set(numbers))
        self.assertTrue({"ATMEGA328P-AU", "RP2040"} <= set(rejected))
        self.assertEqual(len(recommended) + len(rejected), len(self.parts))

    def test_shared_serial_unit_serves_one_role(self):
        part = {
            "pins": {"gpio": ["P1", "P2", "P3", "P4", "P5"]},
            "peripherals": {
                "MSSP_SPI": {"type": "spi", "shares": "MSSP", "signals": {"SCK": ["P1"], "MISO": ["P2"], "MOSI": ["P3"]}},
                "MSSP_I2C": {"type": "i2c", "shares": "MSSP", "signals": {"SCL": ["P4"], "SDA": ["P5"]}},
            },
        }
        spi = {"name": "flash", "type": "spi", "signals": ["SCK", "MISO", "MOSI"]}
        i2c = {"name": "sensor", "type": "i2c", "signals": ["SCL", "SDA"]}
        assignment, _ = assign_pins(part, {"interfaces": [i2c], "gpio": 0})
        self.assertEqual(assignment["sensor"]["peripheral"], "MSSP_I2C")
        assignment, _ = assign_pins(part, {"interfaces": [spi, i2c], "gpio": 0})
        self.assertIsNone(assignment)

    def test_too_many_channels_rejects(self):
        spec = self.spec_with(interfaces=[{"name": "sense", "type": "adc", "channels": 11}])
        _, problems = evaluate_part(self.f103, spec)
        self.assertIn("11 adc channels", problems[0])

    def test_missing_signal_rejects(self):
        spec = self.spec_with(interfaces=[{"name": "modem", "type": "uart", "signals": ["TX", "RX", "RTS"]}])
        _, problems = evaluate_part(self.f103, spec)
        self.assertIn("no uart peripheral", problems[0])


if __name__ == "__main__":
    unittest.main()
