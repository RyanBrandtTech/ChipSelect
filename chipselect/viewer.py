"""Summary Viewer: render the results of a run as a single HTML file.

    python -m chipselect.viewer --recommended recommended_parts.yaml \\
        --requirements Requirements.md --assumptions agent_assumptions.md \\
        --spec formal_specification.yaml [--output summary.html]
"""

import argparse
import sys
from html import escape
from pathlib import Path

import markdown
import yaml

_CSS = """
:root {
  --bg: #f6f7f9; --panel: #ffffff; --text: #1b1f24; --muted: #5d6673;
  --line: #d9dde3; --accent: #0b6bcb; --accent-text: #ffffff; --warn: #9a5b00; --code: #eef0f3;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171b; --panel: #1d2126; --text: #e6e9ed; --muted: #9aa4b1;
    --line: #333a43; --accent: #5aa9f5; --accent-text: #0d1117; --warn: #e3a94a; --code: #262b32;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1000px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 2px; }
.subtitle { color: var(--muted); margin: 0 0 20px; }
[role=tablist] { display: flex; flex-wrap: wrap; gap: 4px; border-bottom: 1px solid var(--line); margin-bottom: 20px; }
[role=tab] { font: inherit; color: var(--muted); background: none; border: 0;
  border-bottom: 2px solid transparent; padding: 8px 14px; margin-bottom: -1px; cursor: pointer; }
[role=tab][aria-selected=true] { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
[role=tabpanel][hidden] { display: none; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; color: var(--muted); }
.sort button { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line);
  padding: 5px 12px; cursor: pointer; }
.sort button:first-child { border-radius: 6px 0 0 6px; }
.sort button:last-child { border-radius: 0 6px 6px 0; border-left: 0; }
.sort button[aria-pressed=true] { background: var(--accent); border-color: var(--accent); color: var(--accent-text); }
.part { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; }
.part header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 24px; align-items: baseline; }
.part h2 { font-size: 17px; margin: 0; }
.part .maker { color: var(--muted); font-weight: 400; font-size: 14px; margin-left: 6px; }
.figures { display: flex; gap: 24px; font-variant-numeric: tabular-nums; }
.figures b { font-size: 17px; }
.figures span { color: var(--muted); font-size: 13px; }
.part p { margin: 6px 0 0; color: var(--muted); }
.facts { display: flex; flex-wrap: wrap; gap: 4px 20px; margin-top: 8px; font-size: 14px; }
.facts span { color: var(--muted); }
.warn { color: var(--warn); margin-top: 8px; font-size: 14px; }
details { margin-top: 10px; }
summary { cursor: pointer; color: var(--accent); font-size: 14px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; margin-top: 8px; font-size: 14px; }
th, td { text-align: left; padding: 4px 16px 4px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 500; }
code, pre { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 13px; }
code { background: var(--code); padding: 1px 4px; border-radius: 3px; }
pre { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; overflow-x: auto; }
pre code { background: none; padding: 0; }
.doc { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 6px 20px 14px; overflow-x: auto; }
.doc pre { background: var(--code); border: 0; }
.empty { color: var(--muted); padding: 24px 0; }
"""

_JS = """
const tabs = [...document.querySelectorAll('[role=tab]')];
function show(tab) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute('aria-selected', on);
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
  }
}
tabs.forEach((tab, i) => {
  tab.addEventListener('click', () => show(tab));
  tab.addEventListener('keydown', e => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (step) { const next = tabs[(i + step + tabs.length) % tabs.length]; show(next); next.focus(); }
  });
});
const list = document.getElementById('parts');
const sorts = {
  price: (a, b) => a.dataset.price - b.dataset.price,
  availability: (a, b) => b.dataset.available - a.dataset.available,
};
function sortBy(key) {
  [...list.children].sort((a, b) => sorts[key](a, b) || a.dataset.part.localeCompare(b.dataset.part))
    .forEach(node => list.appendChild(node));
  for (const b of document.querySelectorAll('.sort button')) b.setAttribute('aria-pressed', b.dataset.sort === key);
}
for (const b of document.querySelectorAll('.sort button')) b.addEventListener('click', () => sortBy(b.dataset.sort));
if (list) sortBy('price');
"""


def _assignment_rows(assignment):
    rows = []
    for name, entry in assignment.items():
        if name == "gpio":
            continue
        if "pins" in entry:
            for signal, pin in entry["pins"].items():
                rows.append((name, f"{entry['peripheral']}.{signal}", pin))
        else:
            for channel in entry["channels"]:
                rows.append((name, channel["signal"], channel["pin"]))
    for pin in assignment.get("gpio", []):
        rows.append(("gpio", "GPIO", pin))
    return rows


def _part_card(part):
    package = part["package"]
    rows = "".join(
        f"<tr><td>{escape(use)}</td><td><code>{escape(signal)}</code></td><td><code>{escape(str(pin))}</code></td></tr>"
        for use, signal, pin in _assignment_rows(part["pin_assignment"])
    )
    special = part.get("special_pins_used") or {}
    warning = ""
    if special:
        used = ", ".join(f"{escape(pin)} ({escape(purpose)})" for pin, purpose in special.items())
        warning = f'<div class="warn">Fits only by using special-function pins: {used}</div>'
    return f"""
<article class="part" data-part="{escape(part['part_number'], quote=True)}" data-price="{part['unit_cost_usd']}" data-available="{part['quantity_available']}">
  <header>
    <h2>{escape(part['part_number'])}<span class="maker">{escape(part['manufacturer'])}</span></h2>
    <div class="figures">
      <div><b>${part['unit_cost_usd']:,.2f}</b> <span>each</span></div>
      <div><b>{part['quantity_available']:,}</b> <span>available</span></div>
    </div>
  </header>
  <p>{escape(part.get('description', ''))}</p>
  <div class="facts">
    <div><span>Package</span> {escape(package['name'])}</div>
    <div><span>Size</span> {package['length_mm']:g} × {package['width_mm']:g} × {package['height_mm']:g} mm</div>
    <div><span>Area</span> {package['area_mm2']:g} mm²</div>
    <div><span>Spare GPIO</span> {part['spare_gpio']}</div>
  </div>
  {warning}
  <details>
    <summary>Pin assignment</summary>
    <div class="scroll"><table><tr><th>Used for</th><th>Signal</th><th>Pin</th></tr>{rows}</table></div>
  </details>
</article>"""


def render(recommended, requirements_md, assumptions_md, spec_yaml):
    """Return the summary HTML for one run."""
    parts = recommended["recommended_parts"]
    count = f"{len(parts)} of {recommended['parts_considered']} parts in the database meet the specification"
    if parts:
        parts_panel = f"""
<div class="toolbar"><span>Sort by</span>
  <div class="sort">
    <button type="button" data-sort="price" aria-pressed="true">Price, lowest first</button><button type="button" data-sort="availability" aria-pressed="false">Availability, most first</button>
  </div>
</div>
<div id="parts">{''.join(_part_card(part) for part in parts)}</div>"""
    else:
        parts_panel = '<p class="empty">No part in the database meets every requirement of the Formal Specification.</p>'

    def to_html(text):
        return markdown.markdown(text, extensions=["tables", "fenced_code"])

    panels = [
        ("parts", "Recommended Parts", parts_panel),
        ("requirements", "Requirements", f'<div class="doc">{to_html(requirements_md)}</div>'),
        ("assumptions", "Agent Assumptions", f'<div class="doc">{to_html(assumptions_md)}</div>'),
        ("spec", "Formal Specification", f"<pre><code>{escape(spec_yaml)}</code></pre>"),
    ]
    tab_buttons = "".join(
        f'<button role="tab" id="tab-{key}" aria-controls="panel-{key}" '
        f'aria-selected="{"true" if index == 0 else "false"}" tabindex="{0 if index == 0 else -1}">{label}</button>'
        for index, (key, label, _) in enumerate(panels)
    )
    tab_panels = "".join(
        f'<section role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}"{"" if index == 0 else " hidden"}>{body}</section>'
        for index, (key, _, body) in enumerate(panels)
    )
    title = escape(recommended["specification"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ChipSelect: {title}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>{title}</h1>
<p class="subtitle">{count}</p>
<div role="tablist" aria-label="Sections">{tab_buttons}</div>
{tab_panels}
</main>
<script>{_JS}</script>
</body>
</html>
"""


def write_summary(recommended_path, requirements_path, assumptions_path, spec_path, output_path):
    """Read the four inputs of a run and write the summary HTML file."""
    html = render(
        yaml.safe_load(Path(recommended_path).read_text()),
        Path(requirements_path).read_text(),
        Path(assumptions_path).read_text(),
        Path(spec_path).read_text(),
    )
    Path(output_path).write_text(html)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render the summary HTML for a ChipSelect run.")
    parser.add_argument("--recommended", default="recommended_parts.yaml")
    parser.add_argument("--requirements", default="Requirements.md")
    parser.add_argument("--assumptions", default="agent_assumptions.md")
    parser.add_argument("--spec", default="formal_specification.yaml")
    parser.add_argument("--output", default="summary.html")
    args = parser.parse_args(argv)

    try:
        write_summary(args.recommended, args.requirements, args.assumptions, args.spec, args.output)
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
