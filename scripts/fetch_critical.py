#!/usr/bin/env python3
"""Download the latest critical-packages.db from ecosyste-ms/critical releases.

Pulls the gzipped SQLite asset from the latest release and decompresses it
into data/. We will eventually augment this DB with our own columns / score
tables, so by default this script refuses to overwrite an existing file
(use --force to replace).

Uses curl for the download (urllib's redirect handling truncates the GitHub
release-asset stream silently — observed 2026-05-14).
"""
import argparse
import gzip
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "ecosyste-ms/critical"
ASSET_NAME = "critical-packages.db.gz"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "data" / "critical-packages.db"),
                    help="output SQLite path (default: data/critical-packages.db)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing DB (custom columns will be lost)")
    args = ap.parse_args()

    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        print(f"refusing to overwrite {out_path} (use --force to replace).", file=sys.stderr)
        print("any custom columns or scores added to this DB will be lost.", file=sys.stderr)
        sys.exit(2)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"querying {RELEASES_URL}")
    req = urllib.request.Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req) as r:
        release = json.load(r)
    tag = release["tag_name"]
    asset = next((a for a in release["assets"] if a["name"] == ASSET_NAME), None)
    if asset is None:
        raise SystemExit(f"asset {ASSET_NAME!r} not found in release {tag}")
    url = asset["browser_download_url"]
    size_mb = asset["size"] / 1024 / 1024
    print(f"downloading {tag} / {ASSET_NAME} ({size_mb:.1f} MB) via curl")

    gz_path = out_path.with_suffix(out_path.suffix + ".gz")
    subprocess.run(["curl", "-L", "--fail", "--silent", "--show-error", "-o", str(gz_path), url],
                   check=True)

    print(f"decompressing -> {out_path}")
    with gzip.open(gz_path, "rb") as src, open(out_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    gz_path.unlink()

    final_mb = out_path.stat().st_size / 1024 / 1024
    print(f"done: {out_path} ({final_mb:.1f} MB), release {tag}")


if __name__ == "__main__":
    main()
