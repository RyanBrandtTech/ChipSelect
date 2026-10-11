# ChipSelect
A recommendation engine for critical part selection in electronics.

Run as a single command-line utility with a Requirements.md as input.

The Requirements.md is an English-language description of the circuit's requirements, which may be incomplete.
The utility runs three separate programs in the following order:
1)  Specification Agent
2)  Part Evaluator
3)  Summary Viewer

Usage

    pip install -r requirements.txt        # PyYAML, jsonschema, Markdown; Claude Code must be installed and logged in
    python -m chipselect examples/sensor_node/Requirements.md

This writes `formal_specification.yaml`, `agent_assumptions.md`, `recommended_parts.yaml` and `summary.html` to an `output/` directory next to the requirements file (change with `--out`).
Use `--skip-agent` to re-run the Part Evaluator and Summary Viewer on a Formal Specification that is already there, and `python -m unittest discover -s tests -t .` to run the tests.

Specification Agent
The Specification Agent is provided with an agent_context.md file, which is a generic set of instructions used as context for the agent.
After injection of this context, the agent reads the Requirements.md file and creates a Formal Specification from it.
If the information in the Requirements.md file is insufficient to create a complete Formal Specification, the agent will note the discrepancy and make reasonable minimal assumptions to complete a Formal Specification.  Any assumptions used are documented in a agent_assumptions.md file which is one output of the utility.
The agent is not allowed to modify the Requirements.md file.  The content and format of the Formal Specification is to be specified in the agent_context.md file.

Part Evaluator
The Part Evaluator is a purely deterministic algorithm (does not use an agent) which takes in the Formal Specification provided by the Specification Agent and produces a recommended_parts.yaml file.
The Part Evaluator references a Parts Database which includes detailed information about all available parts to be considered.
The recommended_parts.yaml output contains a list of all parts from the database which meet all criteria of the Formal Specification.
In addition to the list of parts, the recommended_parts.yaml should also include price and availability data for each included part.

Summary Viewer
The Summary Viewer produces an html file as output whose default selected tab is a visualization of the recommended_parts.yaml file with options for sorting by price (lowest to highest) or availability (most to least).
There are to be three additional tabs:
a)  Requirements (sourced from Requirements.md)
b)  Agent Assumptions (sourced from agent_assumptions.md)
c)  Formal Specification (sourced from the Formal Specification)

TODO:
* ~~Define schema for Parts Database~~ (done: `schemas/part.schema.yaml`, example in `parts/`, check with `python -m chipselect.parts_db parts/`)
* ~~Define schema for Formal Specification including filetype.~~ (done: YAML, `schemas/spec.schema.yaml`, check with `python -m chipselect.spec <file>`)
* ~~Write Part Evaluator script~~ (done: `python -m chipselect.evaluator <spec> --parts parts/`)
* ~~Write basic agent_context.md file~~ (done: `agent_context.md`)
* ~~Define Specification Agent and create a simple way to invoke it to produce the agent_assumptions.md and Formal Specification~~ (done: `python -m chipselect.spec_agent Requirements.md`, runs `claude -p` with no tools)
* ~~Write Summary Viewer script for generating the summary html file.~~ (done: `python -m chipselect.viewer`)
* ~~Write some example Requirements.md files and put them in an examples folder.~~ (done: `examples/`)

The information in the Parts Database is expected to include the following:
* Unit Cost
* Quantity Available (Availability)
* Size (Surface Area)
* Length
* Width
* Height
* Required Power Supplies
* Possible I/O Voltages
* Analog Input Pin Count
* Analog Output Pin Count
* Number of GPIO
* Number of SPI Buses
* Number of I2C Buses
* Number of PWM-Capable Pins
* Number of USB Drivers
* Number of Ethernet PHY MAC Peripherals
* Number of External Flash Memory Controllers
* Bipartite Graph Representation of Internal Peripherals to Device Pin Connectivity (preferred representation is a dictionary of peripheral name -> available pins for multiplexing)

It is expected that many parts in the database may have an excessive number of possible pin uses, but compatibility with a desired application is expected to be frequently constrained by the limited number of available pins, many of which may be used for multiple purposes.
The goal is to have a clear way of evaluating which chips actually fit the desired English-language requirements provided by the user.

Let's work through the TODO items one at a time.  Query the developer to answer questions regarding how things should be implemented.
