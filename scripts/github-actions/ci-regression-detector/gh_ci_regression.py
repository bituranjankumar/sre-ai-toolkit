#!/usr/bin/env python3
"""
gh_ci_regression.py
====================
Detect CI performance regressions introduced by a deploy.

Splits GitHub Actions workflow runs into a "before" and "after" window
around a reference point (a commit SHA or an ISO datetime), then compares
avg / P95 / P99 duration per workflow. Flags any workflow whose average
runtime increased by more than a configurable threshold.

Useful after a dependency bump, Dockerfile change, or test-suite refactor
where you suspect CI got slower but don't have hard numbers yet.

Usage:
    export GITHUB_TOKEN=<your_pat>
    export GITHUB_REPO=grabpay/payment-gateway   # owner/repo

    # Option 1 — split on a deploy datetime
    export SPLIT_AT=2026-05-21T14:30:00Z
    python gh_ci_regression.py

    # Option 2 — split on a commit SHA (uses its push timestamp)
    export SPLIT_SHA=a3f9c2d
    python gh_ci_regression.py

Optional env vars:
    DAYS          Lookback window in days on each side (default: 7)
    TOP_N         Workflows to surface per section (default: 10)
    BRANCH        Filter by branch (default: main)
    THRESHOLD     % increase that counts as a regression (default: 15)
    EXPORT_JSON   Set to 'true' to save a JSON report (default: false)
"""

import os
import sys
import json
import math
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from collections import defaultdict


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_config() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo  = os.environ.get("GITHUB_REPO", "")

    if not token:
        print("ERROR: GITHUB_TOKEN is required.")
        print("       Create a PAT at: github.com/settings/tokens")
        print("       Required scopes: repo (or actions:read)")
        sys.exit(1)
    if not repo:
        print("ERROR: GITHUB_REPO=owner/repo is required.")
        sys.exit(1)

    split_at  = os.environ.get("SPLIT_AT", "")
    split_sha = os.environ.get("SPLIT_SHA", "")

    if not split_at and not split_sha:
        print("ERROR: Set either SPLIT_AT=<ISO datetime> or SPLIT_SHA=<commit SHA>.")
        print("  SPLIT_AT example : 2026-05-21T14:30:00Z")
        print("  SPLIT_SHA example: a3f9c2d")
        sys.exit(1)

    threshold = float(os.environ.get("THRESHOLD", "15"))

    return {
        "token":       token,
        "repo":        repo,
        "split_at":    split_at,
        "split_sha":   split_sha,
        "days":        int(os.environ.get("DAYS", "7")),
        "top_n":       int(os.environ.get("TOP_N", "10")),
        "branch":      os.environ.get("BRANCH", "main"),
        "threshold":   threshold,
        "export_json": os.environ.get("EXPORT_JSON", "false").lower() == "true",
    }


# ---------------------------------------------------------------------------
# GitHub API client (stdlib only)
# ---------------------------------------------------------------------------

class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get(self, path: str, params: dict = None):
        url = f"{self.BASE}{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"ERROR: GitHub API {e.code} for {path}: {body[:300]}")
            sys.exit(1)

    def paginate(self, path: str, params: dict = None, key: str = None) -> list:
        params = dict(params or {})
        params["per_page"] = 100
        page    = 1
        results = []
        while True:
            params["page"] = page
            data  = self.get(path, params)
            items = data.get(key, data) if key and isinstance(data, dict) else data
            if not items:
                break
            results.extend(items)
            if len(items) < 100:
                break
            page += 1
        return results

    def resolve_commit_timestamp(self, repo: str, sha: str) -> datetime:
        """Return the push timestamp for a commit SHA."""
        data = self.get(f"/repos/{repo}/commits/{sha}")
        ts   = data["commit"]["committer"]["date"]   # e.g. "2026-05-21T14:30:00Z"
        return parse_ts(ts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_ts(s: str) -> datetime:
    """Parse GitHub's ISO timestamp (always UTC, always Z-suffixed)."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def duration_seconds(run: dict) -> float | None:
    try:
        start = parse_ts(run["run_started_at"])
        end   = parse_ts(run["updated_at"])
        delta = (end - start).total_seconds()
        return delta if delta > 0 else None
    except Exception:
        return None


def fmt_dur(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def percentile(sorted_data: list[float], p: float) -> float:
    n   = len(sorted_data)
    idx = min(int(math.ceil(p * n)) - 1, n - 1)
    return sorted_data[idx]


def compute_stats(durations: list[float]) -> dict:
    if not durations:
        return {}
    d = sorted(durations)
    n = len(d)
    return {
        "count":   n,
        "avg":     sum(d) / n,
        "p95":     percentile(d, 0.95),
        "p99":     percentile(d, 0.99),
        "min":     d[0],
        "max":     d[-1],
    }


def delta_pct(before: float, after: float) -> float:
    if before == 0:
        return 0.0
    return ((after - before) / before) * 100


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def fetch_all_runs(client: GitHubClient, repo: str, cfg: dict,
                   since: datetime, until: datetime) -> list[dict]:
    """Fetch workflow runs for a repo in [since, until]."""
    params = {
        "branch":  cfg["branch"],
        "status":  "completed",
        "created": f"{since.strftime('%Y-%m-%dT%H:%M:%SZ')}..{until.strftime('%Y-%m-%dT%H:%M:%SZ')}",
    }
    return client.paginate(f"/repos/{repo}/actions/runs", params, key="workflow_runs")


def split_runs(runs: list[dict], split_point: datetime) -> tuple[list, list]:
    """Partition runs into before / after the split point."""
    before, after = [], []
    for run in runs:
        try:
            ts = parse_ts(run["run_started_at"])
        except Exception:
            continue
        (before if ts < split_point else after).append(run)
    return before, after


def group_by_workflow(runs: list[dict]) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        name = run.get("name") or str(run.get("workflow_id", "unknown"))
        dur  = duration_seconds(run)
        if dur is not None:
            groups[name].append(dur)
    return dict(groups)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def regression_label(pct: float, threshold: float) -> str:
    if pct >= threshold * 2:
        return f"  ⚠ REGRESSION +{pct:.0f}%"
    if pct >= threshold:
        return f"  ! slower +{pct:.0f}%"
    if pct <= -threshold:
        return f"  ✓ faster {pct:.0f}%"
    return ""


def print_report(comparison: list[dict], cfg: dict, split_point: datetime) -> None:
    repo    = cfg["repo"]
    branch  = cfg["branch"]
    days    = cfg["days"]
    thr     = cfg["threshold"]

    print()
    print("=" * 76)
    print(f"  GitHub Actions CI Regression Report")
    print(f"  Repo     : {repo}  |  Branch : {branch}")
    print(f"  Split at : {split_point.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Window   : {days} days before / {days} days after")
    print(f"  Threshold: >{thr:.0f}% increase flagged as regression")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 76)

    regressions = [r for r in comparison if r["avg_delta_pct"] >= thr]
    improved    = [r for r in comparison if r["avg_delta_pct"] <= -thr]
    neutral     = [r for r in comparison
                   if -thr < r["avg_delta_pct"] < thr]

    sections = [
        ("REGRESSIONS", regressions, True),
        ("IMPROVEMENTS", improved,   False),
        ("UNCHANGED",    neutral,     False),
    ]

    col = f"  {'Workflow':<38} {'Before avg':>10}  {'After avg':>10}  {'Δ avg':>8}  {'Δ P95':>8}"
    sep = f"  {'-'*38} {'-'*10}  {'-'*10}  {'-'*8}  {'-'*8}"

    for label, rows, show_bar in sections:
        if not rows:
            continue
        print(f"\n  ── {label} ({len(rows)}) ──")
        print(col)
        print(sep)
        for row in sorted(rows, key=lambda x: abs(x["avg_delta_pct"]), reverse=True):
            b    = row["before"]
            a    = row["after"]
            dpct = row["avg_delta_pct"]
            flag = regression_label(dpct, thr)

            before_avg = fmt_dur(b["avg"]) if b else "  —"
            after_avg  = fmt_dur(a["avg"]) if a else "  —"
            delta_avg  = f"{dpct:+.1f}%" if b and a else "  —"
            d_p95_pct  = (f"{delta_pct(b['p95'], a['p95']):+.1f}%"
                          if b and a else "  —")

            name = row["workflow"]
            if len(name) > 37:
                name = name[:34] + "..."

            print(f"  {name:<38} {before_avg:>10}  {after_avg:>10}  {delta_avg:>8}  {d_p95_pct:>8}{flag}")

    # Summary
    print()
    total = len(comparison)
    print(f"  Summary: {total} workflows compared — "
          f"{len(regressions)} regression(s) | "
          f"{len(improved)} improvement(s) | "
          f"{len(neutral)} unchanged")

    if regressions:
        print()
        print(f"  Top regression: '{regressions[0]['workflow']}'")
        print(f"    Before avg {fmt_dur(regressions[0]['before']['avg'])} "
              f"→ After avg {fmt_dur(regressions[0]['after']['avg'])} "
              f"({regressions[0]['avg_delta_pct']:+.1f}%)")
    print()


def export_json(comparison: list[dict], cfg: dict, split_point: datetime) -> None:
    ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"ci_regression_{ts}.json"
    payload  = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo":         cfg["repo"],
        "branch":       cfg["branch"],
        "split_at":     split_point.isoformat(),
        "lookback_days": cfg["days"],
        "threshold_pct": cfg["threshold"],
        "results":      comparison,
    }
    with open(filename, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  JSON report saved -> {filename}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg    = get_config()
    client = GitHubClient(cfg["token"])
    repo   = cfg["repo"]

    # Resolve split point
    if cfg["split_sha"]:
        print(f"\n  Resolving commit {cfg['split_sha']} ...")
        split_point = client.resolve_commit_timestamp(repo, cfg["split_sha"])
        print(f"  Commit timestamp : {split_point.strftime('%Y-%m-%d %H:%M UTC')}")
    else:
        split_point = parse_ts(cfg["split_at"])

    days  = cfg["days"]
    since = split_point - timedelta(days=days)
    until = split_point + timedelta(days=days)

    # Guard against future "until"
    now = datetime.now(timezone.utc)
    if until > now:
        until = now

    print(f"\n  Fetching runs for {repo} ({branch_label(cfg)} branch) ...")
    print(f"  Window : {since.strftime('%Y-%m-%d')} → {until.strftime('%Y-%m-%d')}")

    runs = fetch_all_runs(client, repo, cfg, since, until)
    print(f"  Found  : {len(runs)} completed runs\n")

    if not runs:
        print("  No workflow runs found in this window.")
        print("  Check your token scopes, GITHUB_REPO, and BRANCH settings.\n")
        sys.exit(0)

    before_runs, after_runs = split_runs(runs, split_point)
    print(f"  Before split: {len(before_runs)} runs")
    print(f"  After split : {len(after_runs)} runs")

    before_groups = group_by_workflow(before_runs)
    after_groups  = group_by_workflow(after_runs)

    # Build comparison for all workflows seen in either window
    all_workflows = set(before_groups) | set(after_groups)
    comparison    = []

    for wf in all_workflows:
        b_stats = compute_stats(before_groups.get(wf, []))
        a_stats = compute_stats(after_groups.get(wf,  []))

        if b_stats and a_stats:
            avg_delta = delta_pct(b_stats["avg"], a_stats["avg"])
        elif not b_stats:
            avg_delta = 100.0   # new workflow — appeared after deploy
        else:
            avg_delta = -100.0  # workflow disappeared after deploy

        comparison.append({
            "workflow":       wf,
            "before":         b_stats,
            "after":          a_stats,
            "avg_delta_pct":  round(avg_delta, 2),
        })

    # Sort by delta descending (worst regressions first)
    comparison.sort(key=lambda x: x["avg_delta_pct"], reverse=True)

    print_report(comparison, cfg, split_point)

    if cfg["export_json"]:
        export_json(comparison, cfg, split_point)


def branch_label(cfg: dict) -> str:
    return cfg["branch"]


if __name__ == "__main__":
    main()
