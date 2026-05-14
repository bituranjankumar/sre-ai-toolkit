# GitHub Actions Slow Workflow Analyser

Surface your **top N slowest GitHub Actions workflows** across one or more repositories — ranked by average duration, with P95/P99 stats and failure counts. Zero external dependencies; uses Python stdlib only.

Built for DORA "lead time for changes" analysis and spotting CI bottlenecks before they silently drain engineering productivity.

---

## Why this exists

Slow CI is invisible until someone measures it.

A workflow that takes 18 minutes feels normal after a few weeks — until you realise it's running 40 times a day across 10 repos, burning 120 engineer-hours a month just in wait time.

This script makes that visible in under 30 seconds.

---

## Setup

No dependencies to install — uses Python stdlib only.

```bash
python gh_slow_workflows.py
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | *(required)* | PAT with `repo` scope (or `actions:read` for orgs) |
| `GITHUB_REPO` | — | Single repo e.g. `myorg/myrepo` |
| `GITHUB_ORG` | — | Scan all repos in an org e.g. `myorg` |
| `DAYS` | `14` | Lookback window in days |
| `TOP_N` | `5` | Number of workflows to surface |
| `BRANCH` | `main` | Filter by branch name |
| `STATUS` | `success` | Filter by conclusion: `success`, `failure`, or `all` |
| `EXPORT_JSON` | `false` | Set to `true` to save results as JSON |

---

## Example Usage

```bash
# Single repo — last 14 days on main
export GITHUB_TOKEN=ghp_xxx
export GITHUB_REPO=myorg/backend-api
python gh_slow_workflows.py

# Org-wide scan — last 30 days, top 10
export GITHUB_ORG=myorg
export DAYS=30
export TOP_N=10
python gh_slow_workflows.py

# Find the slowest failing workflows
export GITHUB_REPO=myorg/backend-api
export STATUS=failure
python gh_slow_workflows.py
```

---

## Example Output

```
========================================================================
  Top 5 Slowest GitHub Actions Workflows
  Repos   : myorg/backend-api
  Branch  : main  |  Status: success  |  Last 14 days
  Generated: 2026-05-01 09:15 UTC
========================================================================

  #    Avg        P95        P99        Runs  Workflow
  ---- --------   --------   --------   -----  ------------------------------------
  1    18m 42s    24m 10s    27m 05s      156  Build and Deploy [!!! >15m]
       ████████████████████████████
  2    11m 08s    14m 22s    16m 01s       89  Integration Tests [!! >10m]
       █████████████████
  3    6m 55s     8m 14s     9m 30s       201  Unit Tests + Coverage [! >5m]
       ██████████
  4    3m 12s     4m 01s     4m 44s        94  Lint and Type Check
       ████
  5    1m 48s     2m 10s     2m 29s       178  Security Scan
       ██
```

---

## How to get a GitHub token

1. Go to **github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Create a token with **repo** scope for private repos, or **public\_repo** for public only
3. For org-wide scans, also add **read:org**

---

## Ideas to extend this script

- Add trend comparison: is this workflow slower than last month?
- Send a Slack alert when avg duration exceeds a threshold
- Integrate into a GitHub Action to post a report on every PR
- Build a Grafana dashboard from the JSON export

---

Built by [@bituranjankumar](https://github.com/bituranjankumar) | [LinkedIn](https://www.linkedin.com/in/b-ranjan-kumar)
