# SBOMs

Notes for anyone with access to private SBOMs — your own organization's, or a set of SBOMs from multiple orgs you analyze (a federation, an industry group, a consultancy's clients) — on how to plug them into this pipeline to surface real, environment-specific risk.

This codebase already produces a single `risk = criticality × (1 − health)` score per package using **global** signals from packages.ecosyste.ms. SBOM data lets you replace the global criticality piece with environment-specific criticality (D7), unlock D5/D6 entirely (vulnerability-weighted exposure), and — most usefully — surface packages whose internal importance *outsizes* their global popularity. Those are the hidden risks.

## What you need from the SBOMs

A normalized per-(org, package) table with at least:

| Field | What it is |
|-------|------------|
| `org` | Org identifier (skip if you only have one) |
| `purl` | Canonical package URL (matched against ecosyste.ms's `packages.purl`) |
| `direct_app_count` | Number of the org's applications that **directly** declare this dependency |
| `indirect_app_count` | Number reached only transitively |
| `total_app_count` | Distinct apps using it at all (= union, not sum) |
| `versions_in_use[]` | The versions actually deployed |

Optional but high-value: `runtime_count` (is it actually loaded?), `internet_facing_app_count`, deployment environment tags.

The matching step (SBOM identifier → canonical purl → ecosyste.ms package record) is where most of the practical work is — see "Match quality" at the bottom.

## Three views

### 1. Aggregate view — "what should we worry about across everything?"

Aggregate across **all** SBOMs in your dataset.

```
aggregate_criticality(pkg) = composite_rank_percentile(
    sum_over_orgs(total_app_count),
    count_distinct_orgs_using(pkg),               ← D7 directly
    sum_over_orgs(direct_app_count)
)
risk = aggregate_criticality × (1 − health)
```

Same viz code, just different criticality input. The package that "if it breaks, the most orgs are hurt" floats to the top.

### 2. Per-ecosystem within the aggregate

Same as #1, partitioned by `ecosystem`. Run the ranking inside each ecosystem so npm packages compete with npm packages.

Useful because ecosystems have different threat profiles (npm's churn ≠ maven's stability) and different ownership cultures.

### 3. Per-org view — "what should *this* org worry about?"

Run the same algorithm against a single org's SBOM rows.

```
org_criticality(pkg) = composite_rank_percentile_within(org, (
    direct_app_count,
    indirect_app_count,
    total_app_count
))
risk = org_criticality × (1 − health)
```

Same city/table viz; same filter pills; same score. Each org gets their own picture.

## Outsized risk — the hidden-risk dimension

The interesting one. Some packages are globally popular *and* important to the org — those are obvious risks, well-known. Some are globally popular but unimportant to the org — fine.

The dangerous bucket: **packages where an org's dependence outweighs the package's global popularity.** Example: the package is in the org's top 0.1% by dependency count, but globally it's only in the top 5%. That 50× gap means it's a quietly load-bearing component the rest of the world doesn't pay much attention to — fewer eyes, less likely to be on anyone's radar, more likely to be a single-maintainer/abandoned situation.

```
outsized_factor(org, pkg) = global_rank_percentile(pkg) / org_rank_percentile(org, pkg)
```

- `outsized_factor > 1` → package matters more to this org than to the world
- `outsized_factor >> 1` → hidden risk; this org is exposed in a way nobody else is
- Sort by `outsized_factor × risk` to surface the most dangerous hidden risks first

This works at both the per-org and aggregate levels (aggregate = compare aggregate_criticality vs. global ecosyste.ms rankings).

Likely shapes of packages that fall out of this:
- **Niche industry libraries** — domain-specific, regulatory tooling, vertical-market libraries
- **Legacy adoption** — once-popular libs the org never moved off
- **Internal tools that escaped** — an org used a small OSS lib that never caught on elsewhere
- **Bus-factor traps** — solo-maintainer libs that became load-bearing inside the org's stack

These are exactly the packages where D2 health and D1 tier matter most: nobody outside the org is going to notice if the maintainer drops support.

## How to plug it in

Minimum viable approach, reusing what's already here:

1. Extend `extract_critical_full.py` (or write a sibling `extract_with_sboms.py`) to accept the (org, package) table.
2. Replace the `criticality` field in the emitted JSON with the org-local or aggregate composite. Keep the original `rankings.average` (now renamed e.g. `global_rankings_average`) for the outsized-factor calculation.
3. Add `outsized_factor` as a per-package field in the JSON.
4. The viz template + table template need no changes to render the new criticality — they read `criticality` and don't care where it came from. To surface `outsized_factor`, add a column to `table_template.html` and (optionally) a filter pill or color overlay to `template.html`.
5. For the per-org view, run the pipeline once per org, emit `data/critical-<org>.json`, and build a page per org (`docs/<org>.html`).

`deriveHealth`, `deriveTier`, `deriveSubstitutability` don't change — those are properties of the package, not of who uses it.

## D5 and D6 unlock

Once SBOMs are in, two more dimensions stop being placeholders:

- **D5 actual blast radius** = for each (org, package) pair, sum over advisories of `cvss_score × epss_percentage × (apps_running_vulnerable_version)`. The vuln catalog is already in `data/critical.json`; only `apps_running_vulnerable_version` needs SBOM data to compute.
- **D6 vulnerability concentration** = `count(orgs where pkg has unpatched advisory)` or the weighted version of the same. Cross-org rollup, falls out of the same join.

Both can become additional sort columns in the table view, and either can feed a new health-adjacent color overlay on the city.

## Match quality (the practical hard part)

SBOMs emit identifiers in formats their tooling chose, which is rarely the canonical purl. Expect to handle:

- **CycloneDX** — usually purl-native, mostly clean
- **SPDX** — package metadata is verbose; purl may or may not be present
- **Snyk / proprietary scanner exports** — scanner-specific identifiers, need their own mapping
- **Maven `groupId:artifactId`** vs ecosyste.ms's `org.apache.logging.log4j:log4j-core` style
- **npm `@scope/name`** vs `scope__name` variants
- **Go modules** with version suffixes (`/v2`, `/v3`)
- **Container layers and OS packages** — these are usually noise relative to library packages; consider excluding upfront

Concretely:

1. Normalize every SBOM row to a purl.
2. Left-join against `packages.purl` from the upstream data.
3. **Track unmatched packages explicitly** — the percent matched is your data-quality metric. If it's <80% for an ecosystem, the org-local rankings are unreliable for that ecosystem.
4. Manually triage the top-N unmatched packages by app_count — those are the ones that hurt most if you miss them.

## What stays the same

- D1 tier (ownership)
- D2 health (recency / DDS / maintainers / governance)
- D4 substitutability (size / age / contributors)

These are properties of the package itself, independent of who's using it. The viz derivations in `template.html` and `table_template.html` need no changes.

## What changes

- D3 criticality — re-pivoted to org-local or aggregate
- D5, D6, D7 — unlock for the first time
- New: `outsized_factor` — the gap between internal and global importance
- New: per-org views, aggregate view, and per-ecosystem partitioning of the aggregate

## Visualization additions worth considering

- **Outsized filter pill** in the table view: "only show packages where outsized_factor > N"
- **Color overlay on the city** to mark outsized-risk packages (a stripe, a glow, a swap from green → magenta — pick a hue not used by health)
- **Per-org comparison view** — same package shown at multiple heights, one column per org, so you can spot concentration patterns
- **D7 axis** could replace footprint width: wider base = more orgs use it, regardless of internal app count

## Other pivots worth running

Beyond the main risk story, the data shape supports a lot of analyst-driven cuts. Each of these is a CSV-and-pivot-table exercise, not a separate visualization:

**Ownership and accountability**

- **Risk by tier.** Sum or share of total aggregate risk attributable to each `support_tier` (commercial / foundation / individual / bernies). If 30% of risk sits with "individual" maintainers, that's a very different policy conversation than if it's 5%.
- **Risk by owner.** Top 20 owners by aggregate risk. Identifies systemic concentration — "Google's projects account for X% of our exposure" is a story.
- **Single-owner concentration.** Owners where one entity is responsible for >N% of any single org's risk. The accountability candidates.
- **Free-rider packages.** High `total_app_count` but `funding_links` empty and `dds < 0.3`. Heavily depended on, no funding, one person doing the work. Strong "where to direct support funding" signal.

**Engineering health shape**

- **Bus-factor cliff.** Packages with `commit_stats.dds < 0.3` (one person doing >70% of commits) AND aggregate criticality in the top decile. The actual list of "if this person stops, multiple orgs are hurt."
- **Stale + critical.** `years_since(latest_release_at) > 2` AND high aggregate criticality. Quiet-but-load-bearing.
- **Governance gap.** No `SECURITY.md` AND high criticality. You can't even file a coordinated disclosure cleanly.
- **Recent velocity drop.** Packages where `issue_metadata.past_year_*` activity is sharply below all-time average. Possible maintainer burnout.

**Risk shape**

- **Health × criticality scatter.** Plot every package on (health, criticality). The top-right quadrant is the danger zone; the bottom-right ("low criticality, low health") is fine to ignore; the top-left ("high health, high criticality") is the success story.
- **CVSS-weighted vs EPSS-weighted exposure.** CVSS = theoretical severity; EPSS = likelihood of exploitation. Both lists' top 20 should be looked at — they catch different things.
- **Advisory density.** Advisories per 1000 dependent repos. Surfaces packages that are unusually noisy on the security front for their reach.

**Cross-org concentration** (when you have multiple orgs' SBOMs)

- **Universal dependencies.** Packages present in >X% of orgs. The "everyone uses this" list — if it breaks, every org is affected at once. Highest D7 by definition.
- **Idiosyncratic dependencies.** Packages used by exactly one org. Per-org outliers; the org carrying them is alone on this risk.
- **Pair concentration.** Packages where exactly two orgs use it. Sometimes signals a domain-specific lib worth socializing more broadly, sometimes signals one org copied another's stack.
- **Version drift.** For packages used by multiple orgs, how much variance is there in `versions_in_use`? High variance = if a CVE drops, coordinated response is harder.

**Per-org sanity checks**

- **Match coverage.** What fraction of each org's SBOM rows matched a known ecosyste.ms package? Below ~80% means their ranking is unreliable.
- **Indirect dependence share.** What % of an org's top-criticality packages are reached only indirectly? High share means their developers don't even know what they depend on.
- **Ecosystem mix.** Distribution of an org's packages by `ecosystem`. Useful both for them and for designing shared tooling across orgs.

**Time-series (if you snapshot the CSV monthly)**

- **Risk drift.** Same package, change in (criticality, health, risk) month over month. Identifies projects moving in dangerous directions before they're in active crisis.
- **Adoption velocity.** Packages whose `total_app_count` is growing fast across orgs. Future criticality leading indicator.
- **Advisory aging.** For each open advisory affecting a tracked package, days-since-published. Unpatched + old = priority.
