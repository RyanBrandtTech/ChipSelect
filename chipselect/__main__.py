"""ChipSelect: recommend microcontrollers for an English-language Requirements.md.

    python -m chipselect Requirements.md [--out DIR] [--parts DIR]

Runs the Specification Agent, the Part Evaluator and the Summary Viewer in
that order and writes, into the output directory:

    formal_specification.yaml   agent_assumptions.md
    recommended_parts.yaml      summary.html
"""

import argparse
import sys
from pathlib import Path

import yaml

from chipselect import spec_agent, viewer
from chipselect.evaluator import evaluate
from chipselect.parts_db import PartError, load_parts
from chipselect.spec import SpecError, load_spec

DEFAULT_PARTS = Path(__file__).resolve().parent.parent / "parts"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="chipselect",
        description="Recommend microcontrollers for an English-language requirements file.",
    )
    parser.add_argument("requirements", help="requirements Markdown file (never modified)")
    parser.add_argument("--out", help="output directory (default: output/ next to the requirements file)")
    parser.add_argument("--parts", default=DEFAULT_PARTS, help="Parts Database directory")
    parser.add_argument("--model", help="Claude model for the Specification Agent")
    parser.add_argument(
        "--skip-agent", action="store_true",
        help="reuse the formal_specification.yaml and agent_assumptions.md already in the output directory",
    )
    args = parser.parse_args(argv)

    requirements = Path(args.requirements)
    out = Path(args.out) if args.out else requirements.parent / "output"
    spec_path = out / spec_agent.SPEC_NAME
    assumptions_path = out / spec_agent.ASSUMPTIONS_NAME
    recommended_path = out / "recommended_parts.yaml"
    summary_path = out / "summary.html"

    try:
        parts = load_parts(args.parts)
        if not args.skip_agent:
            spec_agent.run(requirements, out, model=args.model)
        spec = load_spec(spec_path)

        recommended, rejected = evaluate(spec, parts)
        recommended_path.write_text(yaml.safe_dump(
            {
                "specification": spec["title"],
                "parts_considered": len(parts),
                "recommended_parts": recommended,
            },
            sort_keys=False,
        ))
        print(f"Part Evaluator: {len(recommended)} of {len(parts)} parts recommended")
        for number, problems in rejected.items():
            print(f"  rejected {number}: {'; '.join(problems)}")

        viewer.write_summary(recommended_path, requirements, assumptions_path, spec_path, summary_path)
    except (spec_agent.AgentError, SpecError, PartError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Summary Viewer: wrote {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
