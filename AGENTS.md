# AGENTS.md

Notes for AI agents (or anyone) editing this repo.

## What this is

3D cityscape heatmap of OSS projects — a strawman for visualizing OSS project criticality, health, and ownership across ecosystems for any organization analyzing its open-source risk. Originally drafted alongside [Alpha-Omega](https://alpha-omega.dev) discussions. Each cylinder is one OSS project. Visual encoding is in `README.md`.

## Build pipeline

```
python3 scripts/build.py [--data PATH] [--out PATH] [--template PATH]
```

Reads JSON, substitutes it into `scripts/template.html` at the literal placeholder `/*DATA_JSON*/`, writes a self-contained HTML file. The output references `vendor/three.min.js` and `vendor/OrbitControls.js` as siblings (they live in `docs/vendor/`), so `docs/index.html` works on `file://` and on GitHub Pages.

## Conventions

- **Python stdlib only** for build scripts. No jinja2, no click, no requests. Substitution is one `str.replace`; keep it that way.
- **Three.js r128** is vendored. Do not switch to a newer major (r150+) without restructuring around ES modules — the user wants `file://` to work without import maps.
- **Don't switch to D3.js.** The user wrote "d3 web page" but the visualization is 3D cylinders; three.js is correct.
- **No dev server requirement.** The user is often offline / on flaky wifi. Inlined data + local vendor JS is the rule.
- **Fake data must be marked.** `"source": "fake"` in the JSON. Don't fabricate "real-looking" numbers without flagging them.

## When adding a field to projects

1. Add the field to entries in `data/*.json`.
2. Update the "Data format" table in `README.md`.
3. If it should appear in the tooltip, edit the tooltip block in `scripts/template.html`.
4. If it drives a visual property, add a scaling function near the top of the `<script>` block alongside `HEIGHT_SCALE`, `RADIUS_SCALE`, `HEALTH_COLOR`.

## When adding a new dataset

Drop a JSON file in `data/`. Build with `--data data/foo.json --out docs/foo.html`. Multiple datasets via UI toggles in one HTML page is planned (roadmap iteration 3) but not yet implemented.

For procedurally generated data, edit `scripts/gen_fake.py`. Tier-conditioned health distributions, log-normal usage/complexity, and the name pools all live there. Keep `"source"` in the output JSON honestly labeled as `fake` so consumers don't mistake it for real data.

## Interaction model

- Hover → tooltip with name, ecosystem, owner, tier, average rank, health, advisory count.
- Click box → ghost others to GHOST_OPACITY, show detail panel (top-right), label the focused one.
- Click again or click empty space → clear selection.
- Pointerdown→pointerup with <4 px movement is a click; anything more is a drag (OrbitControls handles rotate/pan).
- Labels: top-N by `criticality` shown by default; on selection, only the focused label is visible. On filter, hidden tier/health/ecosystem labels are also suppressed.

## Combined visibility

`applyVisibility()` is the single source of truth for box opacity + label visibility. It AND-combines three filter axes (`activeTiers`, `activeHealth`, `activeEcosystems`) and considers the current selection (`selectedMesh`). Selection overrides filters — clicking a filtered-out box still selects it. When adding new visibility states, extend `applyVisibility()` rather than introducing a parallel mechanism.

## Layout: districts, not centrality

Layout is **two-level**:

1. **Within ecosystem**: projects sorted by `(owner_weight desc, criticality desc)` so same-owner projects are adjacent in the sub-spiral and the most-critical owner anchors the district core. Position = `cluster_center + sunflower(i) + jitter`, where jitter grows for outer-ring `i` (`EDGE_BLEED`) so district edges bleed into neighbors.
2. **Across ecosystems**: each district has radius = `SUB_RADIAL_STEP * sqrt(n) + 2`. Clusters are shuffled (Fisher-Yates, seeded RNG) so they don't visibly sort by size, then placed via simple shelf packing (fill rows until `targetWidth = sqrt(totalArea) * ROW_ASPECT`). Cluster centers are jittered off their grid slots by `CENTER_JITTER_FRAC * radius`.

The seeded RNG (`makeRng(0xC1A1)`) drives all randomness — shuffles, jitters, center drift — so reloads produce identical layouts.

This replaced the earlier sunflower-spiral / dependents-centrality-at-center layout, which formed too smooth a dome at higher project counts (heights correlated with rank correlated with radial position).

## Data pipeline

All data paths emit the same JSON shape (`projects: [{...}]`) so the templates don't branch on source. There are now two real-data paths plus the fake one:

```
fake:    gen_fake.py                       -> data/generated.json

rich:    fetch_critical_full.py            -> data/cache/critical-pages/ + data/critical-full.json (170 MB, gitignored)
         extract_critical_full.py          -> data/critical.json

slim:    fetch_critical.py                 -> data/critical-packages.db (40 MB, gitignored)
         extract_critical.py               -> data/critical.json (legacy)

views:   build.py --data data/critical.json                                       -> docs/index.html
         build.py --data data/critical.json --template scripts/table_template.html --out docs/table.html
```

The **rich path is current** — the live API gives per-package `commit_stats.dds`, `metadata.files.*`, `issue_metadata`, `owner_record.kind`, full `advisories[]`, `rankings.average`, etc. that the slim DB doesn't carry. The slim path is kept around for offline work.

`criticality` is **pre-computed in the extractor** as `1 - log10(rankings.average + 1) / log10(101)` — log scaling because `rankings.average` (0..100, lower = more critical) is heavily skewed (median ~1.86). The slim path computes its own per-ecosystem ranks in SQL since the slim DB doesn't carry `rankings.average`.

`support_tier`, `health`, and `substitutability` are derived **in the templates** (`deriveTier`, `deriveHealth`, `deriveSubstitutability`) because they're tunable visualization rules. Both `template.html` and `table_template.html` carry duplicate copies — keep them in sync. (Refactoring to a shared `docs/derive.js` is a fair follow-up; not done yet.)

### Numeric coercion gotcha

ecosyste.ms returns Postgres NUMERIC fields as JSON **strings** (e.g. `"0.4567"`) to preserve precision. `extract_critical_full.py` has an `fnum()` helper that coerces these (`dds`, `cvss_score`, `epss_percentage`, `rankings.average`). Without coercion, `.toFixed()` calls in the table template throw and the table renders empty.

### Ecosystem exclusions

`extract_critical_full.py` drops `docker`, `actions`, `homebrew`, `bower`, `cpan` at extract time — they aren't libraries in the comparable sense (or sample is too small).

`table_template.html` additionally drops any ecosystem with fewer than `MIN_ECOSYSTEM_SIZE` (currently 100) packages — sparse ecosystems make table sorting/filtering noisy. The city view keeps them.

## Real data: ecosyste-ms/critical (slim SQLite path — legacy)

`scripts/fetch_critical.py` pulls the latest `critical-packages.db.gz` from https://github.com/ecosyste-ms/critical/releases and decompresses to `data/critical-packages.db` (gitignored, ~38 MB). Use `curl` for the download — urllib silently truncates GitHub release-asset redirects.

Schema highlights (release v1.1.20260514):
- **packages** (~9.5k rows): `ecosystem`, `name`, `description`, `repository_url`, `licenses`, `latest_version`, `versions_count`, `downloads`, `dependent_packages_count`, `dependent_repos_count`, `latest_release_at`.
- **advisories** (~4.3k rows): per-package CVEs with `severity`, `cvss_score`.
- **repo_metadata** (~9.3k rows): `owner`, `language`, `stargazers_count`, `forks_count`, `open_issues_count`, `archived`, `fork`. (Stars deliberately not used in the viz; `language` is redundant with `packages.ecosystem`.)
- **versions** (~610k rows).

### User-augmented columns

The user may add custom columns / score tables to this DB to encode their own rankings (e.g., a composite "health" score, a custom "tier" classification). Keep this in mind:

- The fetch script refuses to overwrite without `--force` — protects accidental loss.
- When designing the build script that reads from SQLite, prefer **left-join from `packages`** to a side table (e.g., `scores(package_id PRIMARY KEY, our_health REAL, our_tier TEXT, ...)`) rather than mutating columns in `packages` directly. That way refetching upstream is non-destructive and additions live in tables that survive a refresh.
- If columns are added directly to upstream tables, document the migration in this file and the README.
