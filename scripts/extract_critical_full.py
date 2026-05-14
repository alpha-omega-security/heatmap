#!/usr/bin/env python3
"""Flatten data/critical-full.json (live API records) into data/critical.json
(the shape the viz template consumes).

Excludes ecosystems that aren't libraries in the comparable sense:
  - docker     : packaged services/images, not libraries
  - actions    : GitHub Actions, CI building blocks
  - homebrew   : install recipes
  - bower      : deprecated
  - cpan       : sample too small to be meaningful

Pulls richer derivation inputs than the slim-DB extractor:
  - owner_kind (organization vs user) for D1
  - commit_stats.dds and active_maintainer_count for D2
  - governance file presence (security/code_of_conduct/contributing) for D2
  - repo_size and total_committers for D4
  - max_epss_percentage for D5
  - rankings.average from ecosyste.ms for D3 (lower = more critical, 0..100 percentile)

Writes to data/critical.json with the same shape gen_fake.py emits.
"""
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_ECOSYSTEMS = {"docker", "actions", "homebrew", "bower", "cpan"}
GOVERNANCE_KEYS = ("security", "code_of_conduct", "contributing")


def fnum(x):
    """Coerce to float; return None on failure. Several ecosyste.ms fields
    (dds, cvss_score, epss_percentage) come back as strings because Postgres
    serializes NUMERIC as quoted decimals to preserve precision."""
    if x is None:
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def flatten(p: dict) -> dict:
    rm = p.get("repo_metadata") or {}
    cs = rm.get("commit_stats") or {}
    files = ((rm.get("metadata") or {}).get("files")) or {}
    or_rec = rm.get("owner_record") or {}
    im = p.get("issue_metadata") or {}
    advisories = p.get("advisories") or []
    rankings = p.get("rankings") or {}

    cvss_scores = [fnum(a.get("cvss_score")) for a in advisories]
    cvss_scores = [v for v in cvss_scores if v is not None]
    epss_scores = [fnum(a.get("epss_percentage")) for a in advisories]
    epss_scores = [v for v in epss_scores if v is not None]

    # criticality: rankings.average is 0..100 percentile, lower = more critical, but
    # heavily skewed (median ~1.86, mean ~3.6). Log-scale so heights have spread:
    #   ra=0.002 -> 0.9996,  ra=1 -> 0.85,  ra=10 -> 0.48,  ra=100 -> 0.
    ra = fnum(rankings.get("average"))
    criticality = 0.0 if ra is None else (1.0 - math.log10(ra + 1.0) / math.log10(101.0))

    return {
        "name":                     p.get("name"),
        "ecosystem":                p.get("ecosystem"),
        "purl":                     p.get("purl"),
        "description":              p.get("description"),
        "repository_url":           p.get("repository_url"),
        "licenses":                 p.get("licenses"),
        "latest_version":           p.get("latest_release_number"),
        "versions_count":           p.get("versions_count"),
        "downloads":                p.get("downloads"),
        "downloads_period":         p.get("downloads_period"),
        "dependent_packages_count": p.get("dependent_packages_count"),
        "dependent_repos_count":    p.get("dependent_repos_count"),
        "first_release_at":         p.get("first_release_published_at"),
        "latest_release_at":        p.get("latest_release_published_at"),
        # repo_metadata flattened
        "owner":                    rm.get("owner"),
        "owner_kind":               or_rec.get("kind"),
        "owner_name":               or_rec.get("name"),
        "forks_count":              rm.get("forks_count"),
        "open_issues_count":        rm.get("open_issues_count"),
        "archived":                 bool(rm.get("archived")),
        "fork":                     bool(rm.get("fork")),
        "repo_size":                rm.get("size"),
        # commit_stats (dds is string in raw API)
        "dds":                      fnum(cs.get("dds")),
        "total_committers":         cs.get("total_committers"),
        # issue_metadata
        "active_maintainer_count":  len(im.get("active_maintainers") or []),
        # governance file presence (D2 inputs)
        "has_security_md":          bool(files.get("security")),
        "has_code_of_conduct":      bool(files.get("code_of_conduct")),
        "has_contributing":         bool(files.get("contributing")),
        "governance_files_count":   sum(1 for k in GOVERNANCE_KEYS if files.get(k)),
        # advisory aggregates (D3/D5)
        "advisory_count":           len(advisories),
        "max_cvss_score":           max(cvss_scores) if cvss_scores else None,
        "max_epss_percentage":      max(epss_scores) if epss_scores else None,
        # criticality (D3 input + the height driver)
        "rankings_average":         ra,
        "average_ranking":          ra,  # alias kept for the viz tooltip
        "criticality":              round(criticality, 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", default=str(ROOT / "data" / "critical-full.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "critical.json"))
    ap.add_argument("-n", "--top", type=int, default=None,
                    help="cap to top-N by criticality after exclusions (default: all)")
    args = ap.parse_args()

    raw = json.loads(Path(args.inp).read_text())
    pkgs_in = raw.get("packages") or []
    excluded = sum(1 for p in pkgs_in if p.get("ecosystem") in EXCLUDED_ECOSYSTEMS)
    flat = [flatten(p) for p in pkgs_in if p.get("ecosystem") not in EXCLUDED_ECOSYSTEMS]
    flat.sort(key=lambda p: -(p["criticality"] or 0))
    if args.top:
        flat = flat[:args.top]

    out = {
        "generated_at":    raw.get("generated_at"),
        "source":          f"packages.ecosyste.ms /api/v1/packages/critical "
                           f"(rich; {len(flat)} after excluding ecosystems "
                           f"{sorted(EXCLUDED_ECOSYSTEMS)} = {excluded} dropped)",
        "projects":        flat,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out} ({len(flat)} projects, excluded {excluded})")


if __name__ == "__main__":
    main()
