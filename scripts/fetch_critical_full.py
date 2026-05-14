#!/usr/bin/env python3
"""Download the full critical-packages list from packages.ecosyste.ms.

Hits /api/v1/packages/critical with pagination. Each page contains full
per-package records (rankings, repo_metadata, issue_metadata, advisories) —
the same shape as the per-package detail endpoint.

Pages are cached to data/cache/critical-pages/page-NNNN-ppXXXX.json so
re-runs are cheap and per_page changes don't collide. A second pass
deduplicates by purl across all cache files into data/critical-full.json.

User-Agent embeds an email per ecosyste.ms's rate-limit policy (5000/hr
anonymous; identifying yourself bumps the limit).

If you see 5xx errors, retry with a smaller --per-page. The script will
not auto-shrink mid-run because page numbering shifts when per_page changes.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "critical-pages"
USER_AGENT = "heatmap/1.0 (andrewnez@gmail.com)"
BASE_URL = "https://packages.ecosyste.ms/api/v1/packages/critical"


def fetch(per_page: int, page: int):
    url = f"{BASE_URL}?per_page={per_page}&page={page}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r), dict(r.headers)


def fetch_with_retry(per_page: int, page: int, retries: int = 10):
    delay = 3.0
    for attempt in range(retries):
        try:
            return fetch(per_page, page)
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503, 504, 429) and attempt < retries - 1:
                print(f"  HTTP {e.code}, sleeping {delay:.0f}s (attempt {attempt + 1}/{retries})", file=sys.stderr)
                time.sleep(delay)
                delay = min(delay * 1.7, 60)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            if attempt < retries - 1:
                print(f"  {type(e).__name__}: {e}; sleeping {delay:.0f}s (attempt {attempt + 1}/{retries})", file=sys.stderr)
                time.sleep(delay)
                delay = min(delay * 1.7, 60)
                continue
            raise


def combine(out_path: Path) -> int:
    """Walk all cached pages, dedupe by purl, write combined JSON."""
    seen = {}
    files = sorted(CACHE_DIR.glob("page-*.json"))
    for f in files:
        for pkg in json.loads(f.read_text()):
            purl = pkg.get("purl")
            if purl and purl not in seen:
                seen[purl] = pkg
    payload = {
        "source": "packages.ecosyste.ms /api/v1/packages/critical",
        "package_count": len(seen),
        "packages": list(seen.values()),
    }
    out_path.write_text(json.dumps(payload))
    return len(seen)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between pages")
    ap.add_argument("--combine-only", action="store_true",
                    help="skip fetching, just combine cached pages")
    ap.add_argument("--out", default=str(ROOT / "data" / "critical-full.json"))
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)

    if not args.combine_only:
        page = args.start_page
        total = 0
        while page < args.start_page + args.max_pages:
            cache_file = CACHE_DIR / f"page-{page:04d}-pp{args.per_page}.json"
            if cache_file.exists():
                data = json.loads(cache_file.read_text())
                count = len(data)
                print(f"[cached] page {page:>3}  ({count} pkgs)")
            else:
                print(f"GET page {page:>3} per_page={args.per_page} ... ", end="", flush=True)
                data, _hdrs = fetch_with_retry(args.per_page, page)
                count = len(data)
                cache_file.write_text(json.dumps(data))
                size_mb = cache_file.stat().st_size / 1024 / 1024
                print(f"{count} pkgs, {size_mb:.1f} MB")
                time.sleep(args.sleep)
            total += count
            if count < args.per_page:
                print(f"end of pages (got {count} < {args.per_page})")
                break
            page += 1
        print(f"\nfetched {total} packages across {page - args.start_page + 1} pages")

    n = combine(out_path)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"combined {n} unique packages -> {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
