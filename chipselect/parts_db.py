"""Load and validate the Parts Database (one YAML file per part).

Run as a script to check a database directory:

    python -m chipselect.parts_db parts/
"""

import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from chipselect.signals import BUS_SIGNALS

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "part.schema.yaml"


class PartError(Exception):
    """A part file does not conform to the Parts Database schema."""

    def __init__(self, path, problems):
        self.path = path
        self.problems = problems
        super().__init__(f"{path}: " + "; ".join(problems))


def signal_options(peripheral):
    """The alternative signal -> pins maps of a peripheral (one unless it has pin_options)."""
    return peripheral.get("pin_options") or [peripheral["signals"]]


def derived_counts(part):
    """Compute the headline counts implied by a part's pins and peripherals."""
    by_type = {}
    for peripheral in part["peripherals"].values():
        by_type.setdefault(peripheral["type"], []).append(peripheral)

    def buses(kind):
        return len(by_type.get(kind, []))

    def distinct_pins(kind):
        return len({
            pin
            for peripheral in by_type.get(kind, [])
            for signals in signal_options(peripheral)
            for pins in signals.values()
            for pin in pins
        })

    return {
        "analog_inputs": distinct_pins("adc"),
        "analog_outputs": distinct_pins("dac"),
        "gpio": len(part["pins"]["gpio"]),
        "spi": buses("spi"),
        "i2c": buses("i2c"),
        "pwm_pins": distinct_pins("pwm"),
        "uart": buses("uart"),
        "can": buses("can"),
        "usb": buses("usb"),
        "ethernet": buses("ethernet"),
        "ext_flash": buses("ext_flash"),
    }


def area_mm2(part):
    """Board surface area of the part's package."""
    return part["package"]["length_mm"] * part["package"]["width_mm"]


def _cross_field_problems(part, path):
    problems = []

    if part["part_number"] != path.stem:
        problems.append(f"part_number {part['part_number']!r} does not match file name")

    gpio = set(part["pins"]["gpio"])
    dedicated = set(part["pins"].get("dedicated", []))
    known = gpio | dedicated
    for pin in sorted(gpio & dedicated):
        problems.append(f"pin {pin} is listed as both gpio and dedicated")
    if len(known) > part["package"]["pin_count"]:
        problems.append(
            f"{len(known)} signal pins listed but package has {part['package']['pin_count']} pins"
        )

    for name, peripheral in part["peripherals"].items():
        canonical = BUS_SIGNALS.get(peripheral["type"])
        signals = {}
        for option in signal_options(peripheral):
            for signal, pins in option.items():
                signals.setdefault(signal, []).extend(pins)
        for signal, pins in signals.items():
            if canonical is not None and signal not in canonical:
                problems.append(
                    f"{name}.{signal} is not a canonical {peripheral['type']} signal "
                    f"({', '.join(canonical)})"
                )
            for pin in pins:
                if pin not in known:
                    problems.append(f"{name}.{signal} refers to unknown pin {pin}")
    for pin in part["power"].get("five_volt_tolerant_pins", []):
        if pin not in known:
            problems.append(f"five_volt_tolerant_pins refers to unknown pin {pin}")
    for pin in part["pins"].get("special", {}):
        if pin not in known:
            problems.append(f"pins.special refers to unknown pin {pin}")

    if part["temperature"]["min_c"] > part["temperature"]["max_c"]:
        problems.append("temperature has min_c greater than max_c")
    for supply in part["power"]["supplies"]:
        if supply["min_v"] > supply["max_v"]:
            problems.append(f"supply {supply['name']} has min_v greater than max_v")
    if not any(supply["required"] for supply in part["power"]["supplies"]):
        problems.append("no supply is marked required")

    for key, expected in derived_counts(part).items():
        if part["counts"][key] != expected:
            problems.append(
                f"counts.{key} is {part['counts'][key]} but pins/peripherals imply {expected}"
            )

    return problems


def load_part(path, validator=None):
    """Load one part file, raising PartError if it is invalid."""
    path = Path(path)
    if validator is None:
        validator = Draft202012Validator(yaml.safe_load(SCHEMA_PATH.read_text()))

    try:
        part = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise PartError(path, [f"invalid YAML: {error}"]) from error

    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(part), key=lambda e: list(map(str, e.absolute_path)))
    ]
    if not problems:
        problems = _cross_field_problems(part, path)
    if problems:
        raise PartError(path, problems)
    return part


def load_parts(directory):
    """Load every part in a database directory, keyed by part number.

    Raises PartError for the first invalid part.
    """
    validator = Draft202012Validator(yaml.safe_load(SCHEMA_PATH.read_text()))
    return {
        path.stem: load_part(path, validator)
        for path in sorted(Path(directory).glob("*.yaml"))
    }


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    validator = Draft202012Validator(yaml.safe_load(SCHEMA_PATH.read_text()))
    paths = sorted(Path(argv[1]).glob("*.yaml"))
    failed = 0
    for path in paths:
        try:
            load_part(path, validator)
        except PartError as error:
            failed += 1
            print(f"FAIL {path}")
            for problem in error.problems:
                print(f"     {problem}")
        else:
            print(f"ok   {path}")
    print(f"{len(paths) - failed} of {len(paths)} parts valid")
    return 1 if failed or not paths else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
