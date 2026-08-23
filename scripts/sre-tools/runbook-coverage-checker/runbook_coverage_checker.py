#!/usr/bin/env python3
"""
runbook_coverage_checker.py

Scan an alert inventory and report which alerts have no linked runbook.

Why this exists
---------------
We wired up an AI incident-response tool to our alert pipeline. It kept
surfacing "no runbook found" for roughly half the services. Turns out we had
26 alert rules that had never had a runbook written for them -- some going back
two years. Nobody noticed because the alerts still fired and someone always
figured it out on the call. The AI agent just made the gap impossible to ignore.

This script takes an alert inventory (JSON) and a runbooks directory and
produces a coverage report: which alerts are covered, which aren't, coverage
percent by team, and an uncovered list sorted by severity so you know where to
start.

What counts as "covered"
-------------------------
An alert is considered covered if EITHER:
  (a) it has a non-empty `runbook_url` field in the inventory, OR
  (b) a file exists in the runbooks directory whose name matches the normalised
      alert name (case-insensitive, underscores and spaces replaced with
      hyphens, any extension).

Usage
-----
    python3 runbook_coverage_checker.py alerts.json --runbooks-dir ./runbooks
    python3 runbook_coverage_checker.py alerts.json --runbooks-dir ./runbooks --json
    python3 runbook_coverage_checker.py alerts.json --runbooks-dir ./runbooks --team data-platform

Inventory format (JSON)
-----------------------
[
  {
    "name": "KafkaConsumerLagHigh",
    "severity": "critical",
    "team": "data-platform",
    "runbook_url": "https://wiki.internal/runbooks/kafka-consumer-lag"
  },
  {
    "name": "PodCrashLoopBackOff",
    "severity": "warning",
    "team": "platform-engineering"
  }
]

Fields
  name        (required)  Alert rule name, must be unique
  severity    (required)  critical | warning | info
  team        (required)  Owning team — used for the by-team breakdown
  runbook_url (optional)  If present and non-empty, the alert is covered

Output
------
Console: a coverage summary, uncovered alerts sorted by severity, and a
per-team breakdown table.

Exit codes
  0   All alerts covered
  1   One or more alerts are missing a runbook
  2   Input error (bad inventory file, runbooks dir not found)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "unknown": 3}

# Width constants for the table layout
COL_ALERT  = 38
COL_TEAM   = 24
COL_SEV    = 10
COL_STATUS = 8


def normalise(name: str) -> str:
    """Convert an alert name to the canonical filename stem for matching.

    KafkaConsumerLagHigh  → kafka-consumer-lag-high
    pod_crash_loop_backoff → pod-crash-loop-backoff
    Payments Gateway Timeout → payments-gateway-timeout
    """
    # Insert hyphens between camelCase transitions
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", s)
    # Replace separators with hyphens and lower
    s = re.sub(r"[\s_]+", "-", s).lower()
    # Strip anything non-alphanumeric except hyphens
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s.strip("-")


def load_alerts(path: Path) -> list[dict]:
    try:
        text = path.read_text()
    except FileNotFoundError:
        print(f"error: alert inventory not found: {path}", file=sys.stderr)
        sys.exit(2)
    except OSError as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        sys.exit(2)

    # Optional YAML support — only used if PyYAML is installed
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
        except ImportError:
            print(
                "error: PyYAML is required to read YAML inventories.\n"
                "       Install it with: pip install pyyaml\n"
                "       Or convert your inventory to JSON.",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(2)

    if not isinstance(data, list):
        print("error: inventory must be a JSON array of alert objects", file=sys.stderr)
        sys.exit(2)

    alerts = []
    seen = set()
    for i, item in enumerate(data):
        name = item.get("name", "").strip()
        if not name:
            print(f"warning: alert at index {i} has no 'name' — skipping", file=sys.stderr)
            continue
        if name in seen:
            print(f"warning: duplicate alert name '{name}' — using first occurrence", file=sys.stderr)
            continue
        seen.add(name)
        alerts.append({
            "name":        name,
            "severity":    item.get("severity", "unknown").strip().lower(),
            "team":        item.get("team", "unassigned").strip(),
            "runbook_url": item.get("runbook_url", "").strip(),
        })
    return alerts


def build_runbook_index(runbooks_dir: Path) -> set[str]:
    """Return a set of normalised stem names for every file in runbooks_dir."""
    if not runbooks_dir.is_dir():
        print(f"error: runbooks directory not found: {runbooks_dir}", file=sys.stderr)
        sys.exit(2)
    return {normalise(p.stem) for p in runbooks_dir.iterdir() if p.is_file()}


def check_coverage(alerts: list[dict], runbook_index: set[str]) -> list[dict]:
    results = []
    for alert in alerts:
        if alert["runbook_url"]:
            covered = True
            source = "url"
        elif normalise(alert["name"]) in runbook_index:
            covered = True
            source = "file"
        else:
            covered = False
            source = None
        results.append({**alert, "covered": covered, "source": source})
    return results


def render_text(results: list[dict], team_filter: str | None) -> str:
    if team_filter:
        results = [r for r in results if r["team"].lower() == team_filter.lower()]
        if not results:
            return f"No alerts found for team: {team_filter}"

    total    = len(results)
    covered  = sum(1 for r in results if r["covered"])
    uncovered_list = [r for r in results if not r["covered"]]
    pct      = int(100 * covered / total) if total else 0

    lines = []
    lines.append("RUNBOOK COVERAGE REPORT")
    lines.append("=" * 50)
    lines.append(f"Total alerts : {total}")
    lines.append(f"Covered      : {covered}  ({pct}%)")
    lines.append(f"Uncovered    : {len(uncovered_list)}")
    lines.append("")

    if uncovered_list:
        lines.append("UNCOVERED ALERTS")
        lines.append("-" * 50)
        sorted_uncovered = sorted(
            uncovered_list,
            key=lambda r: (SEVERITY_ORDER.get(r["severity"], 3), r["name"]),
        )
        # Group by severity for readability
        current_sev = None
        for r in sorted_uncovered:
            sev = r["severity"].upper()
            if sev != current_sev:
                lines.append(f"\n  {sev}")
                current_sev = sev
            lines.append(f"    {r['name']:<{COL_ALERT-4}}  {r['team']}")
        lines.append("")

    # Per-team breakdown
    teams: dict[str, dict] = {}
    for r in results:
        t = r["team"]
        if t not in teams:
            teams[t] = {"total": 0, "covered": 0}
        teams[t]["total"] += 1
        if r["covered"]:
            teams[t]["covered"] += 1

    lines.append("BY TEAM")
    lines.append("-" * 50)
    hdr = f"  {'Team':<{COL_TEAM}} {'Total':>6}  {'Covered':>7}  {'Coverage':>9}"
    lines.append(hdr)
    for team, stats in sorted(teams.items(), key=lambda x: x[1]["covered"] / x[1]["total"]):
        t_pct = int(100 * stats["covered"] / stats["total"]) if stats["total"] else 0
        bar = "#" * (t_pct // 10) + "." * (10 - t_pct // 10)
        lines.append(
            f"  {team:<{COL_TEAM}} {stats['total']:>6}  {stats['covered']:>7}  {t_pct:>8}%  [{bar}]"
        )

    if not uncovered_list:
        lines.append("")
        lines.append("All alerts have runbook coverage.")

    return "\n".join(lines)


def render_json(results: list[dict], team_filter: str | None) -> str:
    if team_filter:
        results = [r for r in results if r["team"].lower() == team_filter.lower()]
    total   = len(results)
    covered = sum(1 for r in results if r["covered"])
    return json.dumps(
        {
            "summary": {
                "total":     total,
                "covered":   covered,
                "uncovered": total - covered,
                "coverage_pct": int(100 * covered / total) if total else 0,
            },
            "alerts": results,
        },
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report which alerts are missing a runbook."
    )
    parser.add_argument(
        "inventory",
        type=Path,
        help="JSON (or YAML) file listing alert rules",
    )
    parser.add_argument(
        "--runbooks-dir",
        type=Path,
        default=Path("runbooks"),
        help="Directory containing runbook files (default: ./runbooks)",
    )
    parser.add_argument(
        "--team",
        default=None,
        help="Filter output to a single team",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable table",
    )
    args = parser.parse_args(argv)

    alerts        = load_alerts(args.inventory)
    runbook_index = build_runbook_index(args.runbooks_dir)
    results       = check_coverage(alerts, runbook_index)

    if args.json:
        print(render_json(results, args.team))
    else:
        print(render_text(results, args.team))

    uncovered = [r for r in results if not r["covered"]]
    if args.team:
        uncovered = [r for r in uncovered if r["team"].lower() == args.team.lower()]

    return 1 if uncovered else 0


if __name__ == "__main__":
    raise SystemExit(main())
