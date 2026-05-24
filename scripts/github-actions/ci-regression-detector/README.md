# GitHub Actions CI Regression Detector

Detects CI performance regressions introduced by a deploy.

Splits workflow runs into a **before** and **after** window around a reference point — a commit SHA or an ISO datetime — then compares average / P95 / P99 duration per workflow. Any workflow whose average runtime increased beyond a configurable threshold is flagged as a regression.

Useful after dependency bumps, Dockerfile changes, or test-suite refactors where CI feels slower but you need actual numbers to make the case.

## Requirements

Python 3.10+ · No external dependencies (stdlib only)

## Setup

```bash
export GITHUB_TOKEN=<your_pat>
export GITHUB_REPO=grabpay/payment-gateway
```

PAT requires `repo` scope (or `actions:read` for organisation repos).

## Usage

**Split on a deploy datetime:**
```bash
export SPLIT_AT=2026-05-21T14:30:00Z
python gh_ci_regression.py
```

**Split on a commit SHA** (script resolves the push timestamp automatically):
```bash
export SPLIT_SHA=a3f9c2d
python gh_ci_regression.py
```

## Configuration

| Variable     | Default  | Description                                     |
|--------------|----------|-------------------------------------------------|
| `DAYS`       | `7`      | Lookback window in days on each side of split   |
| `TOP_N`      | `10`     | Max workflows shown per section                 |
| `BRANCH`     | `main`   | Branch filter                                   |
| `THRESHOLD`  | `15`     | % increase that flags a regression              |
| `EXPORT_JSON`| `false`  | Write results to `ci_regression_<ts>.json`      |

## Sample Output

```
============================================================================
  GitHub Actions CI Regression Report
  Repo     : xxx/payment-gateway  |  Branch : main
  Split at : 2026-05-21 14:30 UTC
  Window   : 7 days before / 7 days after
  Threshold: >15% increase flagged as regression
  Generated: 2026-05-24 09:12 UTC
============================================================================

  ── REGRESSIONS (2) ──
  Workflow                               Before avg   After avg     Δ avg     Δ P95
  -------------------------------------- ----------   ----------    ------    ------
  integration-tests                         8m 12s      13m 47s   +67.7%    +71.2%  ⚠ REGRESSION +68%
  lint-and-typecheck                        1m 44s       2m 09s   +23.9%    +18.4%  ! slower +24%

  ── IMPROVEMENTS (1) ──
  Workflow                               Before avg   After avg     Δ avg     Δ T95
  -------------------------------------- ----------   ----------   ------    ------
  unit-tests                                4m 30s       3m 52s   -14.1%     -9.8%  ✓ faster -14%

  ── UNCHANGED (3) ──
  ...

  Summary: 6 workflows compared — 2 regression(s) | 1 improvement(s) | 3 unchanged

  Top regression: 'integration-tests'
    Before avg 8m 12s → After avg 13m 47s (+67.7%)
```

## How It Works

1. Resolves the split point (SHA → timestamp via GitHub Commits API, or parses `SPLIT_AT` directly)
2. Fetches all completed workflow runs in `[split - DAYS, split + DAYS]` using the GitHub Actions API (paginated)
3. Partitions runs into before / after buckets by `run_started_at`
4. Computes avg / P95 / P99 / min / max per workflow in each bucket
5. Calculates percentage delta and flags regressions above `THRESHOLD`

## Tips

- Run immediately after a suspicious deploy, before the before-window rolls out of range
- Use `EXPORT_JSON=true` to pipe results into a Slack webhook or incident ticket
- Combine with the [slow-workflows analyser](../slow-workflows/) to get a full CI health picture
