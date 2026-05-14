# OSS Project Heatmap

3D cityscape visualization of open-source projects. Each project is a rectangular box. Built as a strawman for visualizing OSS project criticality, health, and ownership across ecosystems — aimed at any organization that wants a defensible, data-grounded picture of where their open-source risk is concentrated. Originally drafted to support [Alpha-Omega](https://alpha-omega.dev) risk conversations.

See [`data.md`](./data.md) for the data model — which raw fields from packages.ecosyste.ms feed each of the seven risk dimensions (D1–D7).

| Visual | Encodes | Driven by |
|--------|---------|-----------|
| Color | health — red (bad) → green (good) | derived in JS: average of recency (`latest_release_at`), bus factor (`commit_stats.dds`), active maintainer count, governance file presence (SECURITY.md / CODE_OF_CONDUCT.md / CONTRIBUTING.md). `archived` short-circuits to 0.05 |
| Height | criticality — taller = more critical | `1 − log10(rankings.average + 1) / log10(101)`. Rankings.average is ecosyste.ms's pre-computed composite (downloads + dependents + forks). Log-scaled because the raw distribution is heavily skewed (median ~1.86 on a 0..100 scale) |
| Footprint | substitutability — wider = harder to swap | derived in JS: `0.55·size + 0.40·age + 0.05·contributors` (repo size in KB, years since first release, log of total committers). Range deliberately narrow (1.0..1.5) so footprint stays roughly uniform and tall outliers dominate the eye |
| Position | ecosystem + owner clustering | districts per ecosystem; owner sub-clusters within; centers + edges jittered to break the grid |

## How the single "risk" score is built

The table view's default sort is a single composite **risk** score:

```
risk = criticality × (1 − health)
```

"Popular AND in bad shape" — packages many things depend on that also look neglected or troubled. Both inputs come from raw upstream fields, blended in JS so they're tunable without rebuilding the data:

**criticality** ← `1 − log10(rankings.average + 1) / log10(101)`
- `rankings.average` is ecosyste.ms's pre-computed 0..100 percentile composite over `downloads`, `dependent_packages_count`, `dependent_repos_count`, `forks_count`, `docker_downloads_count`. Lower = more critical.
- Log-scaled because the raw distribution is heavily skewed; without it, almost everything in the critical list reads as "max criticality" and the height signal flattens.

**health** ← mean of four 0..1 sub-scores (`archived` short-circuits to 0.05):
- **recency:** `1 − min(1, years_since(latest_release_at) / 3)`
- **bus factor:** `repo_metadata.commit_stats.dds` (Development Distribution Score; ratio of top committer's contributions to total)
- **maintainer activity:** `min(1, issue_metadata.active_maintainers.length / 3)`
- **governance:** fraction of `{SECURITY.md, CODE_OF_CONDUCT.md, CONTRIBUTING.md}` detected by ecosyste.ms

Advisory data (`advisory_count`, `max_cvss_score`, `epss_percentage`) is captured per package and surfaced in tooltips/details, but isn't currently folded into either composite — that's [data.md](./data.md) D5 territory, blocked on member-org SBOMs for proper weighting.

## Quick start (real data)

The current pipeline pulls the **full critical list with rich per-package data** from packages.ecosyste.ms:

```bash
python3 scripts/fetch_critical_full.py                                           # paginated download -> data/cache/, combine -> data/critical-full.json (~170 MB, gitignored)
python3 scripts/extract_critical_full.py                                         # flatten + derive -> data/critical.json
python3 scripts/build.py --data data/critical.json                               # city view -> docs/index.html
python3 scripts/build.py --data data/critical.json \
    --template scripts/table_template.html --out docs/table.html                 # table view
open docs/index.html        # 3D city
open docs/table.html        # sortable table
```

The two views share the same data and the same JS-side derivations (kept in sync between `template.html` and `table_template.html`). City view is the visual; table view is for the "show me the worst 20 in npm" question.

A legacy slim-DB pipeline is still available (`fetch_critical.py` → `extract_critical.py`) — it pulls a 40 MB SQLite snapshot rather than calling the live API. Skips the rich fields (no `dds`, scorecard, governance file presence, etc.); useful for offline work.

## Fake data (offline / structural)

```bash
python3 scripts/gen_fake.py                              # data/generated.json (default n=150, seed=42)
python3 scripts/build.py --data data/generated.json
```

The fake generator produces the same field shape as `extract_critical_full.py` (and the legacy `extract_critical.py`) — same ecosystem names, same raw columns, same pre-computed `criticality`. The viz template doesn't know whether the data is real or fake.

The hand-curated 31-project `data/sample.json` (older, pre-schema-alignment) still works as `python3 scripts/build.py` without args.

Three.js r128 + OrbitControls are vendored in `docs/vendor/`, so the page works on `file://` with no internet.

## Interactions

- **Drag** to rotate, **scroll** to zoom, **right-drag** to pan.
- **Hover** a box for a tooltip with name, ecosystem, owner, tier, average rank, health, advisory count.
- **Click** a box to focus: all others ghost to 12% opacity, a detail panel appears top-right with the full raw + derived field set and a link to the repo. Click again (or click empty space) to clear.
- **Filter pills** (left side):
  - Tier: `🏢 Commercial · 🏛️ Foundation · 🧑‍💻 Individual · 😎 Bernies`. Bernies = `archived || fork` (every package in the critical list already has traction). Foundation = curated foundation owner list OR `owner_record.kind == "organization"`.
  - Health: `Good ≥0.67 · Mid 0.34–0.67 · Bad <0.34`
  - Ecosystem: derived from the loaded dataset (npm, go, maven, pypi, …)
  - All three filter axes are AND-combined. Click-to-focus overrides filters.
- The top-20 projects by criticality show a name label above their box.

### Table view (`docs/table.html`)

Sortable table with the same data, filters, and JS-side derivations. Cross-linked from the city view's title bar. Default sort: **risk** = `criticality × (1 − health)` — the "show me the worst 20 in npm" answer in one click. Additionally drops any ecosystem with fewer than `MIN_ECOSYSTEM_SIZE = 100` packages because sparse ecosystems make table rankings noisy; the city view keeps them all.

## Repo layout

```
heatmap/
├── data/
│   ├── sample.json              # hand-curated 31-project example (legacy schema)
│   ├── generated.json           # output of gen_fake.py (schema-aligned)
│   ├── critical.json            # output of extract_critical_full.py — what the viz consumes
│   ├── critical-full.json       # raw rich records from the live API (gitignored, ~170 MB)
│   ├── critical-packages.db     # legacy slim-DB snapshot (gitignored, ~40 MB)
│   └── cache/critical-pages/    # paginated API responses, cached for offline reuse (gitignored)
├── scripts/
│   ├── fetch_critical_full.py   # paginated /packages/critical fetch with caching
│   ├── extract_critical_full.py # flatten the rich JSON → data/critical.json (excludes sparse/non-library ecosystems)
│   ├── fetch_critical.py        # legacy: download slim critical-packages.db.gz
│   ├── extract_critical.py      # legacy: SQL → critical.json with our own rankings
│   ├── gen_fake.py              # procedural fake data (same shape as extract)
│   ├── build.py                 # JSON + template → HTML
│   ├── template.html            # 3D city view (three.js)
│   └── table_template.html      # sortable table view
├── docs/
│   ├── index.html               # 3D city (generated, committed for sharing)
│   ├── table.html               # sortable table (generated, committed)
│   └── vendor/
│       ├── three.min.js         # three.js r128, vendored
│       └── OrbitControls.js
├── README.md
├── data.md                      # data-source mapping per working-group dimension (D1-D7)
└── AGENTS.md                    # notes for AI agents working on this repo
```

## Ranking and ecosystem exclusions

**Rich path (current).** `extract_critical_full.py` reads ecosyste.ms's pre-computed `rankings.average` field (a 0..100 percentile, lower = more critical, composite across downloads, dependent packages/repos, forks, etc.) and log-scales it into `criticality ∈ (0, 1]`:

```
criticality = 1 − log10(rankings.average + 1) / log10(101)
```

Log scaling is necessary because the raw distribution is heavily skewed (median ~1.86, mean ~3.6). Linear inversion compresses everything to >0.95 and kills the height signal.

**Slim path (legacy).** `extract_critical.py` operates on the slim SQLite snapshot which doesn't carry `rankings.average`, so it computes its own per-ecosystem ranking in SQL via window functions (`RANK() OVER (PARTITION BY ecosystem ORDER BY metric DESC)` for downloads, dependent_packages_count, dependent_repos_count, forks_count). Cross-ecosystem ranking would be meaningless because most maven/cargo packages have no downloads.

**`gen_fake.py`** mirrors the slim-path ranking algorithm in Python (`attach_rankings`) so fake data flows through the viz identically.

**Ecosystem exclusions.** `extract_critical_full.py` drops `docker`, `actions`, `homebrew`, `bower`, `cpan` outright — they aren't libraries in the comparable sense (or the sample is too small). The table view additionally drops any ecosystem under `MIN_ECOSYSTEM_SIZE` (currently 100 packages).

**Custom columns.** `fetch_critical.py` refuses to overwrite `data/critical-packages.db` without `--force` — protects any custom columns / score tables you add to the SQLite from being clobbered on refetch.

## Layout: districts, not centrality

Each ecosystem becomes a **district** (a sub-spiral of its projects sorted by `(owner, criticality)`). Districts are then packed via simple shelf packing, with the order shuffled (Fisher-Yates, seeded) so they don't visibly sort by size. Cluster centers are jittered off their grid slots, and outer-ring projects within each district get extra position jitter (`EDGE_BLEED`) so districts genuinely bleed into their neighbors rather than tiling cleanly.

Why this works for a 2k-project city: when "most-critical at the center" governed position (earlier iterations), tall buildings formed a smooth dome that hid useful variation. Decoupling position from criticality lets every district have its own internal skyline.

## Tweaking the visualization

The interesting constants live near the top of the `<script>` block in `scripts/template.html`:

```js
const HEIGHT_MAX = 80, HEIGHT_MIN = 1.0, HEIGHT_POWER = 2.5;  // convex curve: mid-rank short, top outliers tower
const RADIUS_SCALE = sub => 1.0 + clamp01(sub) * 0.5;          // substitutability (0..1) -> half-side 1.0..1.5 (narrow on purpose)
const HEALTH_COLOR = h => new THREE.Color('hsl(' + Math.round(h * 120) + ', 75%, 48%)');
const SUB_RADIAL_STEP = 4.5;   // within-cluster spiral spacing
const JITTER = 1.5;            // base per-project jitter
const EDGE_BLEED = 10.0;       // outer-ring projects get this much extra jitter (mixes districts)
const CENTER_JITTER_FRAC = 0.5; // district centers drift up to this fraction of their radius off-grid
const CLUSTER_GAP = -2;        // gap between districts (negative = overlap)
const ROW_ASPECT = 1.3;        // target width/height ratio of the packed layout
const LABEL_TOP_N = 20;
```

Derivation rules also live in the template (and are duplicated in `table_template.html` — keep them in sync):

- `KNOWN_FOUNDATION_OWNERS` and `KNOWN_COMMERCIAL_OWNERS` — curated owner → tier mapping
- `deriveTier(p)` — archived/fork → bernies; commercial-list → commercial; foundation-list or `owner_kind=organization` → foundation; else individual
- `deriveHealth(p)` — averaged blend of recency + `commit_stats.dds` + active maintainer count + governance file presence; `archived` short-circuits to 0.05
- `deriveSubstitutability(p)` — `0.55·log(size) + 0.40·age + 0.05·log(committers)`

Rebuild with `python3 scripts/build.py --data <whatever>` (and pass `--template scripts/table_template.html --out docs/table.html` to rebuild the table too).

## Roadmap

- [x] Iteration 1 — fake dataset + standalone HTML render
- [x] Iteration 2 — programmatic fake data generator + click-to-focus + labels on tallest
- [x] Iteration 3 — filter pills (tier × health × ecosystem) + city layout
- [x] Iteration 4 — real ecosyste-ms/critical data (slim SQLite path)
- [x] Iteration 5 — district-based layout (ecosystem + owner clustering)
- [x] Iteration 6 — full live-API fetch with rich per-package fields (`fetch_critical_full.py` + `extract_critical_full.py`); JS derivations now use commit_stats.dds, governance file presence, owner_kind
- [x] Iteration 7 — sortable table view (`docs/table.html`) for analytic "worst 20 in npm" questions
- [ ] Iteration 8 — port the [weekend-at-bernies](https://github.com/andrew/weekend-at-bernies) `classify.rb` algo for D1 bernies classification
- [ ] Iteration 9 — member-SBOM data layer (D5/D6/D7)

## Mapping to the risk dimensions

See [`data.md`](./data.md) for the full per-dimension data inventory and scoring formulas. Short version:

| Visual / interaction | Risk dimension |
|----------------------|----------------|
| tier filter | D1 — tier of supported library |
| color (health) | D2 — org/community health |
| height (criticality) | D3 — potential blast radius (usage + advisory history) |
| footprint (substitutability) | D4 — substitutability (size + age + contributors proxy) |
| (not yet) | D5 — actual blast radius (needs SBOM-weighted exposure) |
| (not yet) | D6 — vulnerability concentration across the orgs you analyze (needs SBOMs) |
| (not yet) | D7 — library concentration across the orgs you analyze (needs SBOMs) |
