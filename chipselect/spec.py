"""Load and validate a Formal Specification.

Run as a script to check a specification file:

    python -m chipselect.spec formal_specification.yaml
"""

import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from chipselect.signals import BUS_SIGNALS

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "spec.schema.yaml"


class SpecError(Exception):
    """A Formal Specification does not conform to its schema."""

    def __init__(self, path, problems):
        self.path = path
        self.problems = problems
        super().__init__(f"{path}: " + "; ".join(problems))


def _cross_field_problems(spec):
    problems = []

    seen = set()
    for interface in spec["interfaces"]:
        name = interface["name"]
        if name in seen:
            problems.append(f"interface name {name!r} is used more than once")
        seen.add(name)

        canonical = BUS_SIGNALS.get(interface["type"])
        if canonical is not None:
            for signal in interface["signals"]:
                if signal not in canonical:
                    problems.append(
                        f"interface {name!r}: {signal} is not a canonical "
                        f"{interface['type']} signal ({', '.join(canonical)})"
                    )

    temperature = spec["limits"].get("operating_temperature")
    if temperature and temperature["min_c"] > temperature["max_c"]:
        problems.append("limits.operating_temperature has min_c greater than max_c")

    return problems


def load_spec(path):
    """Load a Formal Specification, raising SpecError if it is invalid."""
    path = Path(path)
    validator = Draft202012Validator(yaml.safe_load(SCHEMA_PATH.read_text()))

    try:
        spec = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise SpecError(path, [f"invalid YAML: {error}"]) from error

    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(spec), key=lambda e: list(map(str, e.absolute_path)))
    ]
    if not problems:
        problems = _cross_field_problems(spec)
    if problems:
        raise SpecError(path, problems)
    return spec


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        load_spec(argv[1])
    except SpecError as error:
        print(f"FAIL {error.path}")
        for problem in error.problems:
            print(f"     {problem}")
        return 1
    print(f"ok   {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
