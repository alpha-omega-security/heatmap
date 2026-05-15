# Privacy-Preserving Consortium Analytics (PPCA)

A note on how a group of orgs could share OSS-risk insight *without* sharing their raw SBOMs. This complements [`sboms.md`](./sboms.md) — that doc assumes you already have access to the SBOMs you're analyzing; this one is for the case where you want consortium-level intelligence but each member needs to keep their dependency inventory private.

The short version: each org runs the heatmap pipeline locally, exports a coarsened **bucketed** view of their per-package criticality, and ships that to a neutral aggregator. The aggregator joins under k-anonymity and publishes consortium signal that nobody — not even the aggregator — can attribute back to a specific org.

## Why bother

Raw SBOMs are commercially and operationally sensitive:

- They reveal architecture (which DBs, which auth stacks, which crypto libs)
- They reveal vendor relationships and procurement choices
- They expose attack surface in detail
- "Org X uses package Y at version Z" can be enough to plan an attack

But the *aggregate* insight — "across N member orgs, package P is consistently load-bearing, has 3 unpatched advisories, and shows outsized exposure relative to its global popularity" — is exactly the working-group conversation you want to enable. The output of PPCA is precisely that: aggregate signal with no per-org attribution.

## What each org exports

Each org runs the SBOM pipeline (per `sboms.md`) to get org-local `criticality` and `outsized_factor` per package. Instead of sharing the raw values, they bucket them and emit something like:

```csv
purl, ecosystem, internal_criticality_bucket, outsized_factor_bucket, has_unpatched_advisory
pkg:npm/express, npm, top-1%, normal, false
pkg:npm/log4js, npm, top-5%, outsized-50x, true
pkg:pypi/requests, pypi, top-1%, normal, false
…
```

What's intentionally **not** in the export:

- No `org` identifier
- No `app_count`, `direct_app_count`, `indirect_app_count`
- No `versions_in_use`
- No timestamps that could be cross-referenced with public events
- No dependency-graph structure

What's in:

- `purl` — the package identifier
- `ecosystem` — necessary for cross-ecosystem ranking
- `internal_criticality_bucket` — coarse band, e.g. `{top-0.1%, top-1%, top-5%, top-10%, top-25%, rest}`
- `outsized_factor_bucket` — coarse band, e.g. `{normal, outsized-10x, outsized-50x, outsized-100x+}`
- `has_unpatched_advisory` — boolean

These buckets are coarse enough to defeat reverse-engineering of exact dependency counts, but informative enough to drive useful aggregation.

## What the aggregator publishes

After collecting bucketed exports from N orgs, the aggregator joins on `purl` and applies a **k-anonymity floor** — only publish per-package rows where K+ orgs reported the package (typical K = 3 or 5). Output:

```
purl, contributing_orgs, top-1%_count, top-5%_count, outsized_50x_count, unpatched_advisory_count
pkg:npm/log4js, 7, 4, 6, 3, 2
…
```

Reads as: *log4js shows up in 7 reporting orgs; 4 of them rank it top-1% internally; 3 see outsized exposure relative to its global popularity; 2 have an unpatched advisory.*

The same heatmap code can render this aggregate — `criticality` for the viz becomes a function of those bucket counts (e.g., weighted by bucket position, scaled to 0..1) and the table view sorts/filters work unchanged.

## What leaks vs. what doesn't

**Doesn't leak:**

- Which specific orgs use which packages
- Per-org app counts or version pins
- Internal architecture or dependency graph shape
- Org-specific timing patterns (if exports are batched and de-dated)

**Intentionally leaks (the whole point):**

- Aggregate presence above the K-anonymity floor
- Aggregate criticality bands
- Aggregate vulnerability exposure

**Side channels to be aware of:**

- **Small-N tails.** A package used by exactly K orgs is 100% identified-as-used by all K of them. If the consortium membership is small or known, this is an attribution risk. Mitigations:
  - Bump K higher (5+ instead of 3+) — costs you signal on the long tail
  - Drop or fuzz packages where `contributing_orgs == K` exactly
  - Add a "≤K" floor display rather than the exact count
- **Bucket-edge inference.** Watching how a package moves between criticality buckets across publishing rounds can reveal directional signal about specific orgs. Mitigation: low refresh cadence (monthly, not weekly) and add timing jitter.
- **Out-of-band knowledge.** If you already know an org's tech stack from public sources (job postings, blog posts, conference talks), you can cross-reference even bucketed data. Hard to defeat purely technically; primarily a policy concern about what to publish at all.

## Why outsized_factor is the killer signal here

Because it's the *gap* between internal and global ranking — a relative measure that composes well across orgs without leaking magnitudes. "This package is outsized-50x for 5 of 8 reporting orgs, with no single org accounting for most of it" is exactly the hidden-risk signal you want, and it survives bucketing more gracefully than absolute criticality.

A consortium dashboard sorted by `outsized_factor_count` (orgs reporting outsized exposure) is the equivalent of "what should we collectively be paying attention to that isn't on the public OSS-risk radar." That's the unique value of consortium analytics — global rankings everyone already has; the consortium's own collective blind spots they don't.

## Plugging into this codebase

Three small additions:

1. **`scripts/export_aggregate.py`** — takes a single org's `data/critical.json` (already org-local-pivoted via the SBOM pipeline from `sboms.md`) and emits the bucketed CSV. No org identifier in the output. Configurable bucket boundaries.
2. **`scripts/aggregate_buckets.py`** — takes N bucketed CSVs (one per org), applies K-anonymity floor, emits `data/critical-aggregate.json` in the same shape the viz consumes. Translates bucket counts back into a `criticality` value (weighted average of bucket position) so the templates render unchanged.
3. **`docs/index-aggregate.html` / `docs/table-aggregate.html`** — built from `data/critical-aggregate.json`. Could share templates with the per-org views or have small wording tweaks ("X of N orgs report this in their top 1%" etc.).

## Trust model

**Who runs the aggregator** is the main design question. Three options, in increasing privacy strength:

1. **Neutral steward** — a trusted org runs the aggregator, sees per-org buckets, publishes only the K-anonymized aggregate. Simple to operate; requires the steward be trusted not to log/leak the per-org submissions. A foundation or industry body is a natural fit.
2. **Confidential compute** — the aggregator runs in a TEE (Trusted Execution Environment) that orgs can attest. Same model as #1 but the steward provably can't see the per-org data. More operationally complex; relies on hardware trust.
3. **Secure multi-party computation (MPC)** — orgs jointly compute the aggregate without any party seeing the others' inputs. Cryptographically strongest; significantly more complex to build and operate, and can be slow on large datasets.

For a first pass, option 1 with a clearly-scoped steward and signed submissions is probably the right tradeoff — it's the same trust model that already exists for shared-ISAC-style intelligence sharing, and it works.

## Submission protocol

Keep it simple:

- Each member generates a keypair; aggregator publishes the list of trusted public keys.
- Member runs `export_aggregate.py`, signs the output with their private key, drops the signed bundle in a shared location (S3 bucket, GitHub repo, whatever).
- Aggregator validates signatures, runs `aggregate_buckets.py`, publishes the aggregate.
- No bidirectional protocol; no synchronous coordination; no per-submission negotiation.

## Cadence

Monthly is probably right. SBOMs don't churn fast (most member orgs ship a small handful of new dependencies per month). Weekly invites side-channel inference from delta-watching. Quarterly is probably too slow to be operationally useful for vulnerability response.

## What this enables

- **Consortium "watch list":** packages where multiple member orgs report outsized exposure or unpatched advisories. The list everyone should be staring at without anyone having to confess their stack.
- **Coordinated remediation:** when a CVE drops, the aggregate already tells you roughly how many member orgs are likely affected (without you having to ask each one).
- **Funding direction:** packages that are aggregate-critical but have low health and no commercial backing are obvious targets for shared sponsorship.
- **Baseline drift:** month-over-month change in the aggregate flags rising risk *before* it becomes anyone's individual incident.

## What this does *not* enable

- Telling any individual member "you specifically should worry about X." That conversation has to happen in private with each member's own per-org view.
- Adversarial supply-chain analysis at the level of "which member is vulnerable to attack-vector Y." The aggregate is by design too coarse for that.
- Compliance attestations for individual orgs. PPCA gives you collective intelligence, not per-org assurance.
