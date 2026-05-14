#!/usr/bin/env python3
"""Build a self-contained heatmap HTML page from a JSON dataset.

Reads a JSON file of projects, substitutes it into scripts/template.html,
writes the result to docs/index.html (or wherever --out points).
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "/*DATA_JSON*/"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(ROOT / "data" / "sample.json"),
                    help="input JSON dataset (default: data/sample.json)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "index.html"),
                    help="output HTML path (default: docs/index.html)")
    ap.add_argument("--template", default=str(ROOT / "scripts" / "template.html"),
                    help="template HTML (default: scripts/template.html)")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text())
    template = Path(args.template).read_text()
    if PLACEHOLDER not in template:
        raise SystemExit(f"placeholder {PLACEHOLDER!r} not found in template")
    html = template.replace(PLACEHOLDER, json.dumps(data, indent=2))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"wrote {out_path} ({len(data['projects'])} projects from {args.data})")


if __name__ == "__main__":
    main()
