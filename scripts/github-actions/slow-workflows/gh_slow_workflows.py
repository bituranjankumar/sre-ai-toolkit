#!/usr/bin/env python3
"""
gh_slow_workflows.py
=====================
Identify your top N slowest GitHub Actions workflows across one or more
repositories. Useful for DORA "lead time for changes" analysis and
spotting CI bottlenecks before they become a team-wide pain point.

Usage:
    export GITHUB_TOKEN=<your_pat>
    export GITHUB_REPO=myorg/myrepo        # single repo
    # OR
    export GITHUB_ORG=myorg                # scan all repos in an org

    python gh_slow_workflows.py

Optional env vars:
    DAYS          Lookback window in days (default: 14)
    TOP_N         Workflows to surface (default: 5)
    BRANCH        Filter by branch name (default: main)
    STATUS        Filter by conclusion: success|failure|all (default: success)
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


def get_config() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo  = os.environ.get("GITHUB_REPO", "")
    org   = os.environ.get("GITHUB_ORG", "")

    if not token:
        print("ERROR: GITHUB_TOKEN is required.")
        print("       Create a PAT at: github.com/settings/tokens")
        print("       Required scopes: repo (or actions:read for org use)")
        sys.exit(1)
    if not repo and not org:
        print("ERROR: Set either GITHUB_REPO=owner/repo or GITHUB_ORG=orgname")
        sys.exit(1)

    status = os.environ.get("STATUS", "success").lower()
    if status not in ("success", "failure", "all"):
        print("ERROR: STATUS must be one of: success, failure, all")
        sys.exit(1)

    return {
        "token":       token,
        "repo":        repo,
        "org":         org,
        "days":        int(os.environ.get("DAYS", "14")),
        "top_n":       int(os.environ.get("TOP_N", "5")),
        "branch":      os.environ.get("BRANCH", "main"),
        "status":      status,
        "export_json": os.environ.get("EXPORT_JSON", "false").lower() == "true",
    }


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
            print(f"ERROR: GitHub API {e.code} for {path}: {body[:200]}")
            sys.exit(1)

    def paginate(self, path: str, params: dict = None, key: str = None) -> list:
        params = dict(params or {})
        params["per_page"] = 100
        page, results = 1, []
        while True:
            params["page"] = page
            data = self.get(path, params)
            items = data.get(key, data) if key and isinstance(data, dict) else data
            if not items:
                break
            results.extend(items)
            if len(items) < 100:
                break
            page += 1
        return results

    def get_repos(self, org: str) -> list:
        repos = self.paginate(f"/orgs/{org}/repos", {"type": "all", "sort": "updated"})
        return [r["full_name"] for r in repos if not r.get("archived")]


def fetch_runs(client, repo: str, cfg: dict) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=cfg["days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"branch": cfg["branch"], "created": f">={since}", "per_page": 100}
    if cfg["status"] != "all":
        params["status"] = cfg["status"]
    return client.paginate(f"/repos/{repo}/actions/runs", params, key="workflow_runs")


def duration_seconds(run: dict):
    try:
        fmt   = "%Y-%m-%dT%H:%M:%SZ"
        start = datetime.strptime(run["run_started_at"], fmt).replace(tzinfo=timezone.utc)
        end   = datetime.strptime(run["updated_at"], fmt).replace(tzinfo=timezone.utc)
        delta = (end - start).total_seconds()
        return delta if delta > 0 else None
    except Exception:
        return None


def analyse_runs(runs: list) -> dict:
    groups, failures, names = defaultdict(list), defaultdict(int), {}
    for run in runs:
        name = run.get("name") or str(run.get("workflow_id", "unknown"))
        wid  = str(run.get("workflow_id", name))
        names[wid] = name
        dur = duration_seconds(run)
        if dur is not None:
            groups[wid].append(dur)
        if run.get("conclusion") == "failure":
            failures[wid] += 1

    stats = {}
    for wid, durations in groups.items():
        durations.sort()
        n = len(durations)
        stats[wid] = {
            "name":          names[wid],
            "run_count":     n,
            "avg_sec":       sum(durations) / n,
            "p95_sec":       durations[min(int(math.ceil(0.95 * n)) - 1, n - 1)],
            "p99_sec":       durations[min(int(math.ceil(0.99 * n)) - 1, n - 1)],
            "max_sec":       durations[-1],
            "min_sec":       durations[0],
            "failure_count": failures.get(wid, 0),
        }
    return stats


def fmt_dur(s: float) -> str:
    m = int(s // 60)
    return f"{m}m {int(s % 60):02d}s" if m else f"{int(s)}s"


def severity(avg: float) -> str:
    if avg > 900: return " [!!! >15m]"
    if avg > 600: return " [!! >10m]"
    if avg > 300: return " [! >5m]"
    return ""


def print_report(results: list, cfg: dict, repos: list) -> None:
    print()
    print("=" * 72)
    print(f"  Top {cfg['top_n']} Slowest GitHub Actions Workflows")
    print(f"  Repos   : {', '.join(repos)}")
    print(f"  Branch  : {cfg['branch']}  |  Status: {cfg['status']}  |  Last {cfg['days']} days")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    if not results:
        print("\n  No runs found. Check your token scopes, repo name, and branch.\n")
        return

    max_avg = max(r["avg_sec"] for r in results) or 1
    print(f"\n  {'#':<4} {'Avg':>8}  {'P95':>8}  {'P99':>8}  {'Runs':>5}  Workflow")
    print(f"  {'-'*4} {'-'*8}  {'-'*8}  {'-'*8}  {'-'*5}  {'-'*36}")

    for i, row in enumerate(results, 1):
        fail = f"  ({row['failure_count']} failures)" if row["failure_count"] else ""
        print(
            f"  {i:<4} {fmt_dur(row['avg_sec']):>8}  "
            f"{fmt_dur(row['p95_sec']):>8}  {fmt_dur(row['p99_sec']):>8}  "
            f"{row['run_count']:>5}  {row['name']}{severity(row['avg_sec'])}{fail}"
        )
        print("       " + "\u2588" * int((row["avg_sec"] / max_avg) * 28))
    print()


def export_json(results: list, cfg: dict, repos: list) -> None:
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"slow_workflows_{ts}.json"
    with open(name, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                   "repos": repos, "branch": cfg["branch"],
                   "lookback_days": cfg["days"], "results": results}, f, indent=2)
    print(f"  JSON report saved -> {name}\n")


def main():
    cfg    = get_config()
    client = GitHubClient(cfg["token"])

    if cfg["org"]:
        print(f"\n  Fetching repos for org: {cfg['org']} ...")
        repos = client.get_repos(cfg["org"])
        print(f"  Found {len(repos)} active repos\n")
    else:
        repos = [cfg["repo"]]

    all_stats = {}
    for repo in repos:
        print(f"  Scanning {repo} ...")
        runs  = fetch_runs(client, repo, cfg)
        if not runs:
            continue
        stats = analyse_runs(runs)
        for wid, s in stats.items():
            key = f"{repo}/{s['name']}"
            s["name"] = f"{repo} / {s['name']}" if cfg["org"] else s["name"]
            all_stats[key] = s

    ranked = sorted(all_stats.values(), key=lambda x: x["avg_sec"], reverse=True)[: cfg["top_n"]]
    print_report(ranked, cfg, repos)
    if cfg["export_json"]:
        export_json(ranked, cfg, repos)


if __name__ == "__main__":
    main()
