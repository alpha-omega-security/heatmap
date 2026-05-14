#!/usr/bin/env python3
"""Export data/critical.json to docs/critical.csv with derived fields included.

Mirrors the JS derivations from scripts/template.html so the CSV carries
support_tier, health, substitutability, and risk — the same numbers the
viz uses. Suitable for pivot-table analysis (see sboms.md for ideas).
"""
import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Owner-tier mappings — keep in sync with scripts/template.html.
KNOWN_FOUNDATION_OWNERS = {
    "apache", "eclipse-ee4j", "eclipse", "kubernetes", "etcd-io", "prometheus",
    "cncf", "openjs-foundation", "nodejs", "psf", "pallets", "django", "numfocus",
    "rust-lang", "rails", "ruby",
}
KNOWN_COMMERCIAL_OWNERS = {
    "google", "googleapis", "googlecloudplatform", "microsoft", "azure",
    "facebook", "meta", "aws", "amazonwebservices", "oracle",
    "redhat", "hashicorp", "vercel", "mongodb", "elastic", "snyk", "datadog",
}


def clamp01(x):
    return max(0.0, min(1.0, x))


def years_since(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / (365.25 * 24 * 3600)


def derive_tier(p):
    if p.get("archived") or p.get("fork"):
        return "bernies"
    owner = (p.get("owner") or "").lower()
    if owner in KNOWN_COMMERCIAL_OWNERS:
        return "commercial"
    if owner in KNOWN_FOUNDATION_OWNERS:
        return "foundation"
    if p.get("owner_kind") == "organization":
        return "foundation"
    return "sole_maintainer"


def derive_health(p):
    if p.get("archived"):
        return 0.05
    yrs = years_since(p.get("latest_release_at"))
    recency = 0.3 if yrs is None else clamp01(1 - yrs / 3)
    dds_val = p.get("dds")
    bus = clamp01(float(dds_val)) if dds_val is not None else 0.5
    maint = clamp01((p.get("active_maintainer_count") or 0) / 3)
    gov = clamp01((p.get("governance_files_count") or 0) / 3)
    return (recency + bus + maint + gov) / 4


def derive_substitutability(p):
    size = p.get("repo_size") or 0
    size_score = clamp01(math.log10(size + 1) / 6)
    age_yrs = years_since(p.get("first_release_at"))
    age_score = 0 if age_yrs is None else clamp01(age_yrs / 15)
    committers = p.get("total_committers") or 0
    contrib_score = clamp01(math.log10(committers + 1) / 4)
    return 0.55 * size_score + 0.40 * age_score + 0.05 * contrib_score


COLUMNS = [
    # Identity
    "name", "ecosystem", "purl", "owner", "owner_kind", "owner_name",
    "repository_url", "description",
    # Releases
    "latest_version", "versions_count", "first_release_at", "latest_release_at",
    # Usage signals
    "downloads", "downloads_period",
    "dependent_packages_count", "dependent_repos_count",
    # Repo signals
    "forks_count", "open_issues_count", "archived", "fork",
    "repo_size", "total_committers", "active_maintainer_count",
    # Engineering health
    "dds", "has_security_md", "has_code_of_conduct", "has_contributing",
    "governance_files_count",
    # Vulnerabilities
    "advisory_count", "max_cvss_score", "max_epss_percentage",
    # Compliance
    "licenses",
    # Pre-computed (extractor)
    "rankings_average", "criticality",
    # Derived (mirroring viz JS)
    "support_tier", "health", "substitutability", "risk",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", default=str(ROOT / "data" / "critical.json"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "critical.csv"))
    args = ap.parse_args()

    raw = json.loads(Path(args.inp).read_text())
    projects = raw.get("projects") or []

    rows = []
    for p in projects:
        p = dict(p)  # copy
        p["support_tier"] = derive_tier(p)
        p["health"] = round(derive_health(p), 4)
        p["substitutability"] = round(derive_substitutability(p), 4)
        p["risk"] = round((p.get("criticality") or 0) * (1 - p["health"]), 4)
        rows.append(p)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"wrote {out} ({len(rows)} rows, {len(COLUMNS)} cols)")


if __name__ == "__main__":
    main()
