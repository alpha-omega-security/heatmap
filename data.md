# Data

Fields below are sourced from the live [packages.ecosyste.ms](https://packages.ecosyste.ms) API (per-package endpoint), which joins package + repo + issue + advisory data into one record. Dotted paths show nested JSON. The bundled `critical-packages.db` SQLite snapshot is a thin subset of these — see `AGENTS.md` for which columns it carries.

Each dimension produces **a single number**. The "Score" line below each dimension is the chosen formula or single field. The full menu of available fields is preserved in HTML comments for reference when revisiting these decisions.

## D1 — Tier of supported library

Who owns/maintains the library (accountability): Commercially Supported, Organizationally Supported, or Not Supported.

*we'll have some hardcoded org names here for companies and for foundations*

**Score:** categorical → numeric, picked by first match:

- `archived` OR (`fork` AND has downstream traction) → **bernies** (0.10) (we should use the algo in /Users/andrew/code/andrew/weekend-at-bernies)
- `owner` ∈ `KNOWN_COMMERCIAL` (curated list) → **commercial** (1.00)
- `owner` ∈ `KNOWN_FOUNDATIONS` (curated list) → **foundation** (0.85)
- `repo_metadata.owner_record.kind == "organization"` → **org-supported** (0.60)
- otherwise → **individual** (0.40)

<!--
Full available fields:
- repo_metadata.owner_record.kind ("organization" vs "user" — cleaner than name-matching)
- repo_metadata.owner_record.name (e.g., "Python Software Foundation")
- repo_metadata.owner_record.repositories_count
- repo_metadata.owner_record.funding_links[]
- repo_metadata.owner, repo_metadata.full_name
- repo_metadata.metadata.funding (funding sources declared in repo, e.g. .github/FUNDING.yml)
- funding_links[] (package-level)
- maintainers[] (registry-level publishers, e.g. PyPI/npm accounts)
-->

## D2 — Organizational/community health/maturity

The health and maturity of the project's surrounding org/community — tiered as Foundational, Robust, Thriving, Living, Dormant, Unknown, Bernies.

*https://github.com/andrew/weekend-at-bernies*

**Score:** synthetic blend over fields available for ~all packages (each clamped 0..1, then averaged).

- **recency:** `1 - min(1, years_since(latest_release_published_at) / 3)`
- **bus factor:** `repo_metadata.commit_stats.dds` (already 0..1 when present, else 0.5)
- **maintainer activity:** `min(1, len(issue_metadata.active_maintainers) / 3)`
- **governance:** fraction of `repo_metadata.metadata.files.{security, code_of_conduct, contributing}` that are non-null
- Hard override: `archived == true` → score 0.05.

(OSSF Scorecard fields exist for only ~42% of packages and are deliberately *not* used in the primary score; see the field comment for which checks are useful when surfacing per-package detail.)

<!--
Full available fields:
- repo_metadata.archived, repo_metadata.fork
- repo_metadata.pushed_at, repo_metadata.created_at, repo_metadata.updated_at
- repo_metadata.size, repo_metadata.tags_count, repo_metadata.subscribers_count
- repo_metadata.forks_count, repo_metadata.open_issues_count
- repo_metadata.commit_stats.dds (Development Distribution Score — bus-factor proxy)
- repo_metadata.commit_stats.total_commits, total_committers, mean_commits
- repo_metadata.metadata.files.* — presence of governance/maturity files: security, code_of_conduct, contributing, governance, threat_model, audit, citation, codeowners, support, roadmap
- issue_metadata.issues_count, pull_requests_count, merged_pull_requests_count
- issue_metadata.avg_time_to_close_issue, avg_time_to_close_pull_request
- issue_metadata.past_year_* (all of the above, scoped to the last 12 months)
- issue_metadata.bot_issues_count, bot_pull_requests_count (separates real human activity from bot noise)
- issue_metadata.maintainers[], issue_metadata.active_maintainers[] (per-author counts)
- first_release_published_at, latest_release_published_at, versions_count
- repo_metadata.scorecard.data.score — OSSF Scorecard overall (0-10), ~42% coverage
- repo_metadata.scorecard.data.checks[] useful subset:
  - Code-Review (process maturity)
  - Maintained (recent activity)
  - Branch-Protection (repo discipline)
  - Pinned-Dependencies (supply-chain hygiene)
  - Token-Permissions, Dangerous-Workflow (CI hygiene)
  - Security-Policy (SECURITY.md present — also relates to D5)
-->

## D3 — Potential blast radius (downstream impact)

Risk of the project based on how much it is used and how many vulnerabilities it has already seen — Tier 1/2/3.

*A measure of risk of the project based on how much it is used and how many existing cves has it seen*

**Score:** usage criticality × vulnerability burden.

- `usage = 1 - (rankings.average / N)` where `N` = total ranked packages in the ecosystem (so 1.0 = #1 in ecosystem, 0 = bottom). `rankings.average` is ecosyste.ms's pre-computed composite over downloads, dependents, forks, etc.
- `vuln_factor = 1 + min(1.0, advisory_count × max_cvss_score / 100)` — caps the multiplier so a single 9.8-CVSS advisory roughly doubles the score.
- **`risk = usage × vuln_factor`**

<!--
Full available fields:
- dependent_packages_count, dependent_repos_count
- downloads, downloads_period
- docker_dependents_count, docker_downloads_count
- rankings.average (ecosyste.ms's pre-computed composite ranking)
- rankings.{downloads, dependent_repos_count, dependent_packages_count, stargazers_count, forks_count, docker_downloads_count} (per-metric ranks)
- advisories[] (full per-package array)
- advisories[].severity (LOW / MODERATE / HIGH / CRITICAL)
- advisories[].cvss_score, advisories[].cvss_vector (full CVSS:3.1 string for parsing attack vector / scope / impact)
- advisories[].epss_percentage, advisories[].epss_percentile (exploit probability)
- advisories[].blast_radius (pre-computed per advisory)
- advisories[].classification, published_at, withdrawn_at
- advisories[].packages[].versions[].vulnerable_version_range, first_patched_version
- aggregates: COUNT, MAX(cvss_score), MAX(epss_percentage), SUM(blast_radius) per package
-->

## D4 — Substitutability

Whether an equivalent function is provided by an alternate library (Yes/No).

*here we will make a proxy, instead of taxonomy, we will say the more complex (or large) the project is, the harder it will be to swap*

**Score:** weighted log-blend of size + maturity (higher = harder to swap).

- `size_score = clamp01(log10(repo_metadata.size + 1) / 6)` (1 KB → 0; 1 GB → 1.0)
- `age_score = clamp01(years_since(first_release_published_at) / 15)`
- `contributors_score = clamp01(log10(commit_stats.total_committers + 1) / 4)`
- **`hard_to_swap = 0.55 × size_score + 0.40 × age_score + 0.05 × contributors_score`** — size and age dominate; contributor count is a minor secondary signal.

<!--
Full available fields:
- repo_metadata.size (KB — most direct codebase-size signal)
- versions_count (release count — maturity proxy)
- repo_metadata.tags_count
- repo_metadata.commit_stats.total_commits (cumulative activity)
- repo_metadata.commit_stats.total_committers (number of contributors over project lifetime)
- repo_metadata.created_at and first_release_published_at (project age)
-->

## D5 — Actual blast radius (vulnerability-driven)

The actual blast radius of the vulnerability risk itself — Tier 1/2/3.

*Need SBOMs, skipping for now*

**Score:** *deferred — needs SBOMs to weight vulnerabilities by exposure across the orgs you analyze.*

## D6 — Vulnerability concentration across the orgs you analyze

How many vulnerabilities are associated with the library across your tracked orgs' submission queues (S/M/L).

**Score:** *deferred — needs SBOMs joined per package.*

## D7 — Library concentration across the orgs you analyze

How widely the library is used across the orgs you track (S/M/L) — the dimension that "informs the heatmap."

**Score:** *deferred — needs SBOMs joined per package. Closest stand-in today: `dependent_repos_count` / `rankings.dependent_repos_count`, but that's global Internet reach, not your-fleet reach.*
