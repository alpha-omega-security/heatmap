#!/usr/bin/env python3
"""Extract a heatmap-ready JSON dataset from the ecosyste-ms/critical SQLite DB.

Computes per-ecosystem rankings + composite average_ranking and criticality
in SQL (window functions, RANK with ties), then takes the global top-N by
criticality and dumps JSON in the same shape gen_fake.py emits, so the
viz template doesn't need to know whether the data is real or fake.

Ranking metrics: downloads, dependent_packages_count, dependent_repos_count,
forks_count. NULL values rank last (SQLite places NULLs last in DESC order
by default; RANK ties them at the same position).
"""
import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

QUERY = """
WITH adv_agg AS (
  SELECT package_id,
         COUNT(*) AS advisory_count,
         MAX(cvss_score) AS max_cvss_score
  FROM advisories
  GROUP BY package_id
),
joined AS (
  SELECT
    p.id, p.ecosystem, p.name, p.purl, p.description, p.repository_url,
    p.licenses, p.latest_version, p.versions_count,
    p.downloads, p.downloads_period,
    p.dependent_packages_count, p.dependent_repos_count,
    p.first_release_at, p.latest_release_at,
    rm.owner, rm.forks_count, rm.open_issues_count, rm.archived, rm.fork,
    COALESCE(adv.advisory_count, 0) AS advisory_count,
    adv.max_cvss_score
  FROM packages p
  LEFT JOIN repo_metadata rm ON rm.package_id = p.id
  LEFT JOIN adv_agg adv ON adv.package_id = p.id
),
ranked AS (
  SELECT
    *,
    RANK() OVER (PARTITION BY ecosystem ORDER BY downloads DESC)                  AS rank_downloads,
    RANK() OVER (PARTITION BY ecosystem ORDER BY dependent_packages_count DESC)   AS rank_dep_pkgs,
    RANK() OVER (PARTITION BY ecosystem ORDER BY dependent_repos_count DESC)      AS rank_dep_repos,
    RANK() OVER (PARTITION BY ecosystem ORDER BY forks_count DESC)                AS rank_forks,
    COUNT(*) OVER (PARTITION BY ecosystem)                                        AS ecosystem_size
  FROM joined
),
scored AS (
  SELECT
    *,
    (rank_downloads + rank_dep_pkgs + rank_dep_repos + rank_forks) / 4.0
      AS average_ranking,
    (ecosystem_size
       - (rank_downloads + rank_dep_pkgs + rank_dep_repos + rank_forks) / 4.0
       + 1.0) * 1.0 / ecosystem_size
      AS criticality
  FROM ranked
)
SELECT *
FROM scored
ORDER BY criticality DESC
LIMIT ?;
"""

# Fields that map directly to the viz JSON. Order is preserved in output.
FIELDS = [
    "name", "ecosystem", "purl", "description", "repository_url",
    "licenses", "latest_version", "versions_count",
    "downloads", "downloads_period",
    "dependent_packages_count", "dependent_repos_count",
    "first_release_at", "latest_release_at",
    "owner", "forks_count", "open_issues_count", "archived", "fork",
    "advisory_count", "max_cvss_score",
    "average_ranking", "criticality",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "data" / "critical-packages.db"))
    ap.add_argument("--out", default=str(ROOT / "data" / "critical.json"))
    ap.add_argument("-n", "--top", type=int, default=300,
                    help="number of projects to emit (default 300)")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found at {db_path}. Run scripts/fetch_critical.py first.")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(QUERY, (args.top,)).fetchall()
    build_info = conn.execute("SELECT built_at, package_count FROM build_info LIMIT 1").fetchone()
    conn.close()

    projects = []
    for r in rows:
        d = {f: r[f] for f in FIELDS}
        # Cast integer flags to JSON booleans for the viz.
        d["archived"] = bool(d["archived"]) if d["archived"] is not None else False
        d["fork"] = bool(d["fork"]) if d["fork"] is not None else False
        # Round derived floats for legibility.
        d["average_ranking"] = round(d["average_ranking"], 2)
        d["criticality"] = round(d["criticality"], 4)
        projects.append(d)

    out = {
        "generated_at": str(date.today()),
        "source": (f"ecosyste-ms/critical (top {len(projects)} by criticality, "
                   f"per-ecosystem ranking; upstream built_at={build_info['built_at']}, "
                   f"package_count={build_info['package_count']})"),
        "projects": projects,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"wrote {out_path} ({len(projects)} projects from {db_path})")


if __name__ == "__main__":
    main()
