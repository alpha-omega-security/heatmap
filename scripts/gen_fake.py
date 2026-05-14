#!/usr/bin/env python3
"""Generate a fake heatmap dataset that mirrors the ecosyste-ms/critical
SQLite schema.

Each project has the raw columns we'd get from joining `packages` +
`repo_metadata` + an aggregated count of `advisories`. Derived fields
(health, support_tier, average_ranking) are computed in the visualization
template, so this generator stays a 1:1 stand-in for the real SQL query.

Distributions are tuned to be roughly believable for typical OSS:
  - dependent_repos_count, dependent_packages_count, downloads, forks: log-normal
  - latest_release_at: heavily weighted toward recent (last 2y), long tail
  - archived ~5%, fork ~3%
  - advisories: most have 0; ~10% have 1-3; ~3% have 5+
  - downloads is null for ecosystems where the registry doesn't expose it
    (matches the real DB, where only npm/pypi/etc. have download counts).
"""
import argparse
import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Real ecosyste-ms ecosystem names + approximate proportions from v1.1.20260514.
ECOSYSTEMS = [
    ("npm",       24),
    ("rubygems",  10),
    ("cargo",      9),
    ("maven",      7),
    ("hackage",    7),
    ("go",         7),
    ("pypi",       6),
    ("packagist",  5),
    ("nuget",      4),
    ("conda",      4),
]
# Ecosystems that publish download counts (others get NULL).
DOWNLOAD_ECOSYSTEMS = {"npm", "pypi", "rubygems", "cargo", "nuget"}

# Owner tier hints. Names match real GitHub orgs so the JS-side derivation
# (KNOWN_FOUNDATION_OWNERS / KNOWN_COMMERCIAL_OWNERS in the template) maps them.
FOUNDATION_OWNERS = [
    "apache", "eclipse-ee4j", "eclipse", "kubernetes", "etcd-io",
    "prometheus", "cncf", "openjs-foundation", "nodejs", "psf",
    "pallets", "django", "numfocus", "rust-lang", "rails", "ruby",
]
COMMERCIAL_OWNERS = [
    "google", "googleapis", "googlecloudplatform", "microsoft", "azure",
    "facebook", "meta", "aws", "amazonwebservices",
    "oracle", "redhat", "hashicorp", "vercel", "mongodb",
    "elastic", "snyk", "datadog",
]
INDIVIDUAL_OWNERS = [
    "jdoe", "msmith", "kbrown", "rwilson", "alex123", "lchen", "mtanaka",
    "pgomez", "skim", "njohnson", "edavis", "tlee", "hpatel", "ymori",
    "rdas", "fkrause", "obekele", "wnguyen", "qsato", "vsmirnov",
    "iruiz", "agarcia", "bpark", "cbrennan", "dmoreau", "eokafor",
    "fhamada", "gmehta", "hadams", "iclark",
]

# Tier weights drive how often we pick from each owner pool.
TIER_WEIGHTS = [("foundation", 25), ("commercial", 15), ("individual", 60)]

LICENSES = ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC", "BSD-2-Clause",
            "MPL-2.0", "GPL-3.0", "LGPL-3.0", "Unlicense", None]

PREFIXES = ["lib", "py", "node-", "go-", "rb-", "ng-", "hyper", "fast",
            "micro", "macro", "ultra", "json", "yaml", "auth", "redis",
            "mongo", "kafka", "swift", "tiny", "deep", "smart", "neo",
            "open", "secure", "cloud", "edge", "snap", "rapid", "lean",
            "blue", "iron"]
ROOTS = ["parser", "router", "cache", "queue", "logger", "validator",
         "loader", "store", "client", "server", "proxy", "broker", "engine",
         "kit", "core", "utils", "api", "db", "auth", "sync", "stream",
         "buffer", "watcher", "manager", "scheduler", "monitor", "tracer",
         "metrics", "config", "schema", "codec", "reactor", "hash",
         "crypto", "compiler", "render", "diff", "patch", "lint", "shell",
         "fmt", "test", "mock", "bench"]
SUFFIXES = ["", "-core", "-extra", "2", "-lite", "-plus", "-x", "-next",
            "-mini", "", "", "", "-pro", "-cli", "-sdk"]

NOW = datetime.now(timezone.utc)


def gen_name(rng, used):
    for _ in range(200):
        n = rng.choice(PREFIXES) + rng.choice(ROOTS) + rng.choice(SUFFIXES)
        if n not in used:
            used.add(n)
            return n
    raise RuntimeError("name space exhausted")


def lognormal_int(rng, mu, sigma, lo=0, hi=None):
    v = int(round(math.exp(rng.gauss(mu, sigma))))
    v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def random_release_date(rng):
    """Weight toward recent dates: ~70% within the last 2 years, long tail to ~7 years."""
    if rng.random() < 0.7:
        days_ago = rng.randint(0, 730)
    elif rng.random() < 0.7:
        days_ago = rng.randint(730, 365 * 4)
    else:
        days_ago = rng.randint(365 * 4, 365 * 7)
    d = NOW - timedelta(days=days_ago)
    return d.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def gen_project(rng, used):
    eco_keys = [e for e, _ in ECOSYSTEMS]
    eco_weights = [w for _, w in ECOSYSTEMS]
    ecosystem = rng.choices(eco_keys, weights=eco_weights, k=1)[0]
    name = gen_name(rng, used)

    tier_keys = [t for t, _ in TIER_WEIGHTS]
    tier_weights = [w for _, w in TIER_WEIGHTS]
    tier = rng.choices(tier_keys, weights=tier_weights, k=1)[0]
    if tier == "foundation":
        owner = rng.choice(FOUNDATION_OWNERS)
    elif tier == "commercial":
        owner = rng.choice(COMMERCIAL_OWNERS)
    else:
        owner = rng.choice(INDIVIDUAL_OWNERS)

    archived = rng.random() < 0.05
    fork = rng.random() < 0.03

    # Counts. Tier biases magnitude: commercial/foundation projects trend bigger.
    base_mu_dep = {"commercial": 6.0, "foundation": 5.5, "individual": 4.0}[tier]
    dep_repos = lognormal_int(rng, base_mu_dep + 0.5, 1.6, lo=0)
    dep_pkgs = lognormal_int(rng, base_mu_dep - 1.0, 1.5, lo=0)

    if ecosystem in DOWNLOAD_ECOSYSTEMS:
        downloads = lognormal_int(rng, base_mu_dep + 4.5, 2.2, lo=0)
        downloads_period = "last-month"
    else:
        downloads = None
        downloads_period = None

    versions_count = lognormal_int(rng, 2.8, 1.0, lo=1, hi=2000)
    forks_count = lognormal_int(rng, base_mu_dep - 1.5, 1.5, lo=0)
    open_issues = lognormal_int(rng, base_mu_dep - 2.0, 1.4, lo=0)

    # Most packages: 0 advisories. Long tail.
    if rng.random() < 0.10:
        advisory_count = lognormal_int(rng, 1.0, 0.8, lo=1, hi=40)
        max_cvss_score = round(rng.uniform(3.0, 10.0), 1)
    else:
        advisory_count = 0
        max_cvss_score = None

    latest_release_at = None if rng.random() < 0.02 else random_release_date(rng)

    # repo_metadata is missing for ~3% of packages in real data (no public git host).
    has_repo = rng.random() > 0.03
    if not has_repo:
        owner = None
        forks_count = None
        open_issues = None
        repository_url = None
    else:
        repository_url = f"https://github.com/{owner}/{name}"

    return {
        "name": name,
        "ecosystem": ecosystem,
        "purl": f"pkg:{ecosystem}/{name}",
        "description": None,
        "repository_url": repository_url,
        "licenses": rng.choice(LICENSES),
        "latest_version": f"{rng.randint(0, 9)}.{rng.randint(0, 30)}.{rng.randint(0, 50)}",
        "versions_count": versions_count,
        "downloads": downloads,
        "downloads_period": downloads_period,
        "dependent_packages_count": dep_pkgs,
        "dependent_repos_count": dep_repos,
        "first_release_at": None,
        "latest_release_at": latest_release_at,
        "owner": owner,
        "forks_count": forks_count,
        "open_issues_count": open_issues,
        "archived": archived,
        "fork": fork,
        "advisory_count": advisory_count,
        "max_cvss_score": max_cvss_score,
    }


RANKING_METRICS = ["downloads", "dependent_packages_count",
                   "dependent_repos_count", "forks_count"]


def attach_rankings(projects):
    """Compute per-ecosystem average_ranking and criticality, mirroring the
    SQL extractor in scripts/extract_critical.py (RANK with ties; NULLs last)."""
    from collections import defaultdict
    by_eco = defaultdict(list)
    for p in projects:
        by_eco[p["ecosystem"]].append(p)

    for eco_projects in by_eco.values():
        n = len(eco_projects)
        for m in RANKING_METRICS:
            # Sort desc with NULL/None as worst (placed last).
            ordered = sorted(eco_projects,
                             key=lambda p: (p.get(m) is None, -(p.get(m) or 0)))
            prev_key = object()
            rank = 0
            for i, p in enumerate(ordered):
                v = p.get(m)
                key = (v is None, v)
                if key != prev_key:
                    rank = i + 1
                    prev_key = key
                p.setdefault("_ranks", {})[m] = rank
        for p in eco_projects:
            avg = sum(p["_ranks"][m] for m in RANKING_METRICS) / len(RANKING_METRICS)
            p["average_ranking"] = round(avg, 2)
            p["criticality"] = round((n - avg + 1) / n, 4)
            del p["_ranks"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--count", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(ROOT / "data" / "generated.json"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    used = set()
    projects = [gen_project(rng, used) for _ in range(args.count)]
    attach_rankings(projects)

    out = {
        "generated_at": str(date.today()),
        "source": f"fake (schema-aligned, n={args.count}, seed={args.seed})",
        "notes": ("Procedurally generated. Raw fields mirror ecosyste-ms/critical SQLite "
                  "(packages + repo_metadata + advisories aggregate). average_ranking and "
                  "criticality are pre-computed per-ecosystem; health and support_tier are "
                  "derived in the viz template."),
        "projects": projects,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"wrote {out_path} ({len(projects)} projects, seed={args.seed})")


if __name__ == "__main__":
    main()
