"""Part Evaluator: list the parts that meet every criterion of a Formal Specification.

    python -m chipselect.evaluator formal_specification.yaml \\
        [--parts parts/] [--output recommended_parts.yaml]

Deterministic; no agent is involved. A part is recommended only if it passes
every scalar limit and its interface signals and GPIO can all be placed on
distinct pins.
"""

import argparse
import math
import sys
from collections import deque
from itertools import product

import yaml

from chipselect.parts_db import PartError, area_mm2, load_parts, signal_options
from chipselect.signals import CHANNEL_TYPES
from chipselect.spec import SpecError, load_spec


def scalar_problems(part, spec):
    """Reasons the part fails the specification's limits and power requirements."""
    problems = []
    limits = spec["limits"]
    package = part["package"]

    def at_most(label, value, key, unit):
        if key in limits and value > limits[key]:
            problems.append(f"{label} {value:g} {unit} exceeds limit of {limits[key]:g} {unit}")

    def at_least(label, value, key, unit):
        if key in limits and value < limits[key]:
            problems.append(f"{label} {value:g} {unit} is below required {limits[key]:g} {unit}")

    longer, shorter = sorted((package["length_mm"], package["width_mm"]), reverse=True)
    at_most("unit cost", part["unit_cost_usd"], "max_unit_cost_usd", "USD")
    at_least("quantity available", part["quantity_available"], "min_quantity_available", "units")
    at_most("area", area_mm2(part), "max_area_mm2", "mm2")
    at_most("longer side", longer, "max_length_mm", "mm")
    at_most("shorter side", shorter, "max_width_mm", "mm")
    at_most("height", package["height_mm"], "max_height_mm", "mm")
    at_least("flash", part["flash_kb"], "min_flash_kb", "KB")
    at_least("RAM", part["ram_kb"], "min_ram_kb", "KB")
    at_least("max clock", part["max_clock_mhz"], "min_clock_mhz", "MHz")

    if "cores" in limits and part["core"] not in limits["cores"]:
        problems.append(f"core {part['core']} is not one of {', '.join(limits['cores'])}")

    wanted = limits.get("operating_temperature")
    have = part["temperature"]
    if wanted and (have["min_c"] > wanted["min_c"] or have["max_c"] < wanted["max_c"]):
        problems.append(
            f"operating range {have['min_c']:g} to {have['max_c']:g} C does not cover "
            f"{wanted['min_c']:g} to {wanted['max_c']:g} C"
        )

    rails = spec["power"]["supply_rails_v"]
    for supply in part["power"]["supplies"]:
        if supply["required"] and not any(supply["min_v"] <= rail <= supply["max_v"] for rail in rails):
            problems.append(
                f"supply {supply['name']} ({supply['min_v']:g} to {supply['max_v']:g} V) "
                f"accepts none of the available rails"
            )

    io_voltage = spec["power"]["io_voltage_v"]
    if not any(math.isclose(io_voltage, v, abs_tol=1e-6) for v in part["power"]["io_voltages"]):
        problems.append(f"I/O voltage {io_voltage:g} V is not supported")

    return problems


class _Flow:
    """Integer max-flow by shortest augmenting paths, on a small graph.

    Shortest paths take a free pin before rerouting an earlier signal, so
    signals stay on their first-listed (default) pins unless they must move.
    """

    def __init__(self):
        self.capacity = {}
        self.adjacent = {}

    def edge(self, a, b, capacity):
        self.capacity[a, b] = self.capacity.get((a, b), 0) + capacity
        self.capacity.setdefault((b, a), 0)
        self.adjacent.setdefault(a, []).append(b)
        self.adjacent.setdefault(b, []).append(a)

    def _augment(self, source, sink):
        parent = {source: None}
        queue = deque([source])
        while queue and sink not in parent:
            node = queue.popleft()
            for nxt in self.adjacent.get(node, []):
                if nxt not in parent and self.capacity[node, nxt] > 0:
                    parent[nxt] = node
                    queue.append(nxt)
        if sink not in parent:
            return False
        node = sink
        while parent[node] is not None:
            self.capacity[parent[node], node] -= 1
            self.capacity[node, parent[node]] += 1
            node = parent[node]
        return True

    def run(self, source, sink):
        total = 0
        while self._augment(source, sink):
            total += 1
        return total


def _place(part, spec, buses, chosen, channel_maps, avoid):
    """Place signals on distinct pins for one choice of bus peripherals.

    `chosen` gives a (peripheral, signal map) for each of the first
    len(chosen) entries of `buses`. Channel interfaces and GPIO are included
    only when `channel_maps` (peripheral -> signal map) is given. Pins in
    `avoid` are never used. Returns the pin assignment, or None if the pins
    cannot all be placed.
    """
    flow = _Flow()
    demand = 0
    pins_used = set()

    def signal_node(peripheral, signal, pins):
        node = ("signal", peripheral, signal)
        if node not in flow.adjacent:
            for pin in pins:
                if pin not in avoid:
                    flow.edge(node, ("pin", pin), 1)
                    pins_used.add(pin)
        return node

    for interface, (peripheral, signals) in zip(buses, chosen):
        for signal in interface["signals"]:
            flow.edge("source", signal_node(peripheral, signal, signals[signal]), 1)
            demand += 1

    with_rest = channel_maps is not None
    channels = [i for i in spec["interfaces"] if i["type"] in CHANNEL_TYPES] if with_rest else []
    for interface in channels:
        group = ("group", interface["name"])
        flow.edge("source", group, interface["channels"])
        demand += interface["channels"]
        for name, peripheral in part["peripherals"].items():
            if peripheral["type"] == interface["type"]:
                for signal, pins in channel_maps[name].items():
                    node = signal_node(name, signal, pins)
                    # One unit out of each signal keeps channels independent
                    # even when two groups of the same type compete for it.
                    hub = ("channel", name, signal)
                    if hub not in flow.adjacent:
                        flow.edge(hub, node, 1)
                    flow.edge(group, hub, 1)

    if with_rest and spec["gpio"]:
        flow.edge("source", "gpio", spec["gpio"])
        demand += spec["gpio"]
        # Offer the pins with the fewest peripheral functions first.
        functions = {}
        for peripheral in part["peripherals"].values():
            for signals in signal_options(peripheral):
                for pins in signals.values():
                    for pin in pins:
                        functions[pin] = functions.get(pin, 0) + 1
        special = part["pins"].get("special", {})
        for pin in sorted(part["pins"]["gpio"], key=lambda pin: (pin in special, functions.get(pin, 0))):
            if pin not in avoid:
                flow.edge("gpio", ("pin", pin), 1)
                pins_used.add(pin)

    for pin in sorted(pins_used):
        flow.edge(("pin", pin), "sink", 1)

    if flow.run("source", "sink") < demand:
        return None

    def pin_of(node):
        return next(
            b[1] for b in flow.adjacent[node]
            if b[0] == "pin" and flow.capacity[b, node] > 0
        )

    assignment = {}
    for interface, (peripheral, _) in zip(buses, chosen):
        assignment[interface["name"]] = {
            "peripheral": peripheral,
            "pins": {s: pin_of(("signal", peripheral, s)) for s in interface["signals"]},
        }
    for interface in channels:
        group = ("group", interface["name"])
        assignment[interface["name"]] = {
            "channels": [
                {"signal": f"{hub[1]}.{hub[2]}", "pin": pin_of(("signal", hub[1], hub[2]))}
                for hub in flow.adjacent[group]
                if hub != "source" and flow.capacity[hub, group] > 0
            ]
        }
    if with_rest:
        assignment["gpio"] = [
            node[1] for node in flow.adjacent.get("gpio", [])
            if node != "source" and flow.capacity[node, "gpio"] > 0
        ]
    return assignment


def _search(part, spec, avoid):
    """Find a pin assignment that uses no pin in `avoid`, or None."""
    buses = [i for i in spec["interfaces"] if i["type"] not in CHANNEL_TYPES]
    order = {name: index for index, name in enumerate(part["peripherals"])}

    # (peripheral, signal map) choices able to host each bus interface.
    candidates = [
        [
            (name, signals)
            for name, peripheral in part["peripherals"].items()
            if peripheral["type"] == interface["type"]
            for signals in signal_options(peripheral)
            if all(signal in signals for signal in interface["signals"])
        ]
        for interface in buses
    ]

    # Channel peripherals pick one pin option each; try every combination.
    channel_types = {i["type"] for i in spec["interfaces"] if i["type"] in CHANNEL_TYPES}
    channel_names = [n for n, p in part["peripherals"].items() if p["type"] in channel_types]
    channel_choices = [
        dict(zip(channel_names, combination))
        for combination in product(*(signal_options(part["peripherals"][n]) for n in channel_names))
    ]

    def search(chosen):
        if len(chosen) == len(buses):
            for channel_maps in channel_choices:
                result = _place(part, spec, buses, chosen, channel_maps, avoid)
                if result is not None:
                    return result
            return None
        interface = buses[len(chosen)]
        for name, signals in candidates[len(chosen)]:
            if any(name == taken for taken, _ in chosen):
                continue
            # Interchangeable interfaces: try each set of peripherals once.
            if any(
                earlier["type"] == interface["type"]
                and sorted(earlier["signals"]) == sorted(interface["signals"])
                and order[taken] > order[name]
                for earlier, (taken, _) in zip(buses, chosen)
            ):
                continue
            extended = chosen + [(name, signals)]
            if _place(part, spec, buses, extended, None, avoid) is None:
                continue
            result = search(extended)
            if result is not None:
                return result
        return None

    return search([])


def assign_pins(part, spec):
    """Find a conflict-free pin assignment for the specification on the part.

    Special pins (debug, boot, crystal) are used only if the part does not
    fit without them. Returns (assignment, None) on success or (None, reason)
    on failure.
    """
    for interface in spec["interfaces"]:
        peripherals = [p for p in part["peripherals"].values() if p["type"] == interface["type"]]
        if interface["type"] in CHANNEL_TYPES:
            available = sum(
                len({signal for option in signal_options(p) for signal in option}) for p in peripherals
            )
            if available < interface["channels"]:
                return None, (
                    f"interface {interface['name']!r} needs {interface['channels']} "
                    f"{interface['type']} channels but the part has {available}"
                )
        elif not any(
            all(signal in option for signal in interface["signals"])
            for p in peripherals for option in signal_options(p)
        ):
            return None, (
                f"no {interface['type']} peripheral provides "
                f"{', '.join(interface['signals'])} for interface {interface['name']!r}"
            )

    special = set(part["pins"].get("special", {}))
    assignment = _search(part, spec, special)
    if assignment is None and special:
        assignment = _search(part, spec, set())
    if assignment is None:
        return None, "interface signals and GPIO cannot all be placed on distinct pins"
    return assignment, None


def evaluate_part(part, spec):
    """Return (pin assignment, []) if the part fits, else (None, reasons)."""
    problems = scalar_problems(part, spec)
    if problems:
        return None, problems
    assignment, reason = assign_pins(part, spec)
    if assignment is None:
        return None, [reason]
    return assignment, []


def evaluate(spec, parts):
    """Evaluate every part. Returns (recommended entries, {part number: reasons})."""
    recommended = []
    rejected = {}
    for number in sorted(parts):
        part = parts[number]
        assignment, problems = evaluate_part(part, spec)
        if assignment is None:
            rejected[number] = problems
            continue
        package = part["package"]
        special = part["pins"].get("special", {})
        used = _pins_used(assignment)
        recommended.append({
            "part_number": number,
            "manufacturer": part["manufacturer"],
            "description": part.get("description", ""),
            "unit_cost_usd": part["unit_cost_usd"],
            "quantity_available": part["quantity_available"],
            "package": {
                "name": package["name"],
                "length_mm": package["length_mm"],
                "width_mm": package["width_mm"],
                "height_mm": package["height_mm"],
                "area_mm2": round(area_mm2(part), 4),
            },
            "spare_gpio": len(set(part["pins"]["gpio"]) - set(special) - used),
            "special_pins_used": {pin: special[pin] for pin in sorted(used & set(special))},
            "pin_assignment": assignment,
        })
    return recommended, rejected


def _pins_used(assignment):
    used = set(assignment["gpio"])
    for name, entry in assignment.items():
        if name == "gpio":
            continue
        used.update(entry.get("pins", {}).values())
        used.update(channel["pin"] for channel in entry.get("channels", []))
    return used


def main(argv=None):
    parser = argparse.ArgumentParser(description="List the parts that meet a Formal Specification.")
    parser.add_argument("spec", help="Formal Specification YAML file")
    parser.add_argument("--parts", default="parts", help="Parts Database directory (default: parts)")
    parser.add_argument("--output", default="recommended_parts.yaml", help="output file (default: recommended_parts.yaml)")
    args = parser.parse_args(argv)

    try:
        spec = load_spec(args.spec)
        parts = load_parts(args.parts)
    except (SpecError, PartError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    recommended, rejected = evaluate(spec, parts)
    with open(args.output, "w") as output:
        yaml.safe_dump(
            {
                "specification": spec["title"],
                "parts_considered": len(parts),
                "recommended_parts": recommended,
            },
            output,
            sort_keys=False,
        )

    for number, problems in rejected.items():
        print(f"rejected {number}")
        for problem in problems:
            print(f"         {problem}")
    print(f"{len(recommended)} of {len(parts)} parts recommended -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
