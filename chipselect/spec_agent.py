"""Specification Agent: turn a Requirements.md into a Formal Specification.

    python -m chipselect.spec_agent Requirements.md [--out DIR]

Runs Claude Code headless with agent_context.md as its system prompt and
writes formal_specification.yaml and agent_assumptions.md. The agent is given
no tools, so it cannot touch Requirements.md or any other file; this program
writes the two outputs from the agent's reply.
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from chipselect.spec import SpecError, load_spec

CONTEXT_PATH = Path(__file__).resolve().parent / "agent_context.md"
SPEC_NAME = "formal_specification.yaml"
ASSUMPTIONS_NAME = "agent_assumptions.md"
MAX_ATTEMPTS = 3

_REPLY = re.compile(
    r"^=== formal_specification\.yaml ===\s*\n(?P<spec>.*?)"
    r"^=== agent_assumptions\.md ===\s*\n(?P<assumptions>.*?)"
    r"^=== end ===\s*$",
    re.DOTALL | re.MULTILINE,
)


class AgentError(Exception):
    """The Specification Agent could not be run or never produced a valid result."""


def _ask(prompt, context_path, model):
    command = [
        "claude", "--print",
        "--system-prompt-file", str(context_path),
        "--tools", "",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if model:
        command += ["--model", model]
    try:
        result = subprocess.run(command, input=prompt, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise AgentError("the `claude` command was not found; install Claude Code") from error
    if result.returncode != 0:
        raise AgentError(f"claude exited with status {result.returncode}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def _check(reply):
    """Return (spec text, assumptions text, problems) for an agent reply."""
    match = _REPLY.search(reply)
    if not match:
        return None, None, ["the reply does not follow the required reply format with its three marker lines"]
    spec_text = match["spec"].strip() + "\n"
    assumptions_text = match["assumptions"].strip() + "\n"

    with tempfile.TemporaryDirectory() as scratch:
        candidate = Path(scratch) / SPEC_NAME
        candidate.write_text(spec_text)
        try:
            load_spec(candidate)
        except SpecError as error:
            return spec_text, assumptions_text, error.problems
    return spec_text, assumptions_text, []


def run(requirements_path, out_dir, context_path=CONTEXT_PATH, model=None, log=print):
    """Produce the Formal Specification and assumptions for a requirements file.

    Returns the paths of the two files written. Raises AgentError if no valid
    specification is obtained within MAX_ATTEMPTS.
    """
    requirements = Path(requirements_path).read_text()
    prompt = f"Here is the requirements document.\n\n<requirements>\n{requirements}\n</requirements>\n"

    request = prompt
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"Specification Agent: attempt {attempt} of {MAX_ATTEMPTS}")
        reply = _ask(request, context_path, model)
        spec_text, assumptions_text, problems = _check(reply)
        if not problems:
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            spec_path = out_dir / SPEC_NAME
            assumptions_path = out_dir / ASSUMPTIONS_NAME
            spec_path.write_text(spec_text)
            assumptions_path.write_text(assumptions_text)
            return spec_path, assumptions_path

        for problem in problems:
            log(f"  rejected: {problem}")
        request = (
            f"{prompt}\nYour previous reply was rejected.\n\n<previous_reply>\n{reply}\n</previous_reply>\n\n"
            "Problems found by the validator:\n" + "\n".join(f"- {p}" for p in problems) + "\n"
        )

    raise AgentError(f"no valid Formal Specification after {MAX_ATTEMPTS} attempts")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a Formal Specification from a Requirements.md.")
    parser.add_argument("requirements", help="requirements Markdown file")
    parser.add_argument("--out", default=".", help="directory for the two output files (default: current directory)")
    parser.add_argument("--context", default=CONTEXT_PATH, help="agent context file (default: chipselect/agent_context.md)")
    parser.add_argument("--model", help="Claude model to use (default: Claude Code's configured model)")
    args = parser.parse_args(argv)

    try:
        spec_path, assumptions_path = run(args.requirements, args.out, args.context, args.model)
    except (AgentError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {spec_path}\nwrote {assumptions_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
