#!/usr/bin/env python3
"""
datadog_monitor_gen.py

Generate Terraform (datadog_monitor) resource blocks from a small JSON
service spec, instead of hand-writing HCL for every new endpoint/queue/job.

Why this exists
---------------
Every time platform-eng onboards a new service, someone copies an existing
monitors.tf, renames the service, fat-fingers a threshold, and ships it.
We've shipped at least two monitors that alerted on the wrong service because
of exactly that copy-paste step. This script takes a short JSON spec per
service and emits ready-to-review HCL with consistent naming, tags,
notification routing, and the boring-but-important defaults
(notify_no_data, renotify_interval, evaluation_delay) that are easy to forget.

It does NOT call the Datadog API and does NOT run terraform apply — it only
generates .tf files for you to review and commit. Treat the output as a
draft, not gospel.

Usage
-----
    python3 datadog_monitor_gen.py specs/rides-dispatch-svc.json
    python3 datadog_monitor_gen.py specs/rides-dispatch-svc.json -o monitors/

Spec format (JSON)
------------------
{
  "service": "rides-dispatch-svc",
  "team": "mobility-platform",
  "env": "production",
  "notify": ["@slack-mobility-platform-alerts", "@pagerduty-mobility-platform"],
  "monitors": [
    {
      "name": "high error rate",
      "type": "metric alert",
      "query": "sum(last_5m):sum:trace.http.request.errors{service:rides-dispatch-svc,env:production}.as_count() / sum:trace.http.request.hits{service:rides-dispatch-svc,env:production}.as_count() > 0.02",
      "message": "Error rate above 2% for 5 minutes. Check the dispatch matching queue first — this is usually a downstream timeout, not us.",
      "critical": 0.02,
      "warning": 0.01,
      "evaluation_delay": 300
    },
    {
      "name": "p99 latency breach",
      "type": "metric alert",
      "query": "percentile(last_10m):p99:trace.http.request.duration{service:rides-dispatch-svc,env:production} > 1.5",
      "message": "p99 latency over 1.5s for 10 minutes.",
      "critical": 1.5,
      "warning": 1.0
    }
  ]
}

Output
------
One .tf file per service, named after the service
(e.g. rides-dispatch-svc_monitors.tf), containing one datadog_monitor
resource block per entry in "monitors".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Defaults applied when a monitor entry doesn't specify them. These are the
# settings that get forgotten in copy-paste and end up biting us during an
# incident (e.g. a monitor that silently stops re-notifying after the first page).
DEFAULT_EVALUATION_DELAY = 60
DEFAULT_NOTIFY_NO_DATA = "false"
DEFAULT_NO_DATA_TIMEFRAME = 20
DEFAULT_RENOTIFY_INTERVAL = 60  # minutes
DEFAULT_NOTIFY_AUDIT = "false"


def slugify(value: str) -> str:
    """Turn 'rides-dispatch-svc high error rate' into a safe Terraform
    resource name: 'rides_dispatch_svc_high_error_rate'."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def render_notify_block(channels: list[str]) -> str:
    """Datadog monitor messages route through @-mentions appended to the
    message body — not a separate HCL field. We append them here so authors
    don't have to remember the syntax (or worse, forget it and the page goes
    nowhere)."""
    if not channels:
        return ""
    return "\n\n" + " ".join(channels)


def render_monitor(service: str, env: str, team: str, notify: list[str], spec: dict) -> str:
    name = spec["name"]
    monitor_type = spec.get("type", "metric alert")
    query = spec["query"]
    message = spec.get("message", "").rstrip()
    full_message = message + render_notify_block(notify)

    resource_name = slugify(f"{service}_{name}")
    full_title = f"[{env}] {service} — {name}"

    critical = spec.get("critical")
    warning = spec.get("warning")
    if critical is None:
        raise ValueError(f"monitor '{name}' for {service} is missing a 'critical' threshold")

    thresholds_lines = [f'    critical = {critical}']
    if warning is not None:
        thresholds_lines.append(f'    warning  = {warning}')

    evaluation_delay = spec.get("evaluation_delay", DEFAULT_EVALUATION_DELAY)
    no_data_timeframe = spec.get("no_data_timeframe", DEFAULT_NO_DATA_TIMEFRAME)
    renotify_interval = spec.get("renotify_interval", DEFAULT_RENOTIFY_INTERVAL)
    notify_no_data = spec.get("notify_no_data", DEFAULT_NOTIFY_NO_DATA)

    tags = [f"service:{service}", f"env:{env}", f"team:{team}", "managed-by:terraform"]
    tags_block = ",\n".join(f'    "{tag}"' for tag in tags)

    return f'''resource "datadog_monitor" "{resource_name}" {{
  name    = "{full_title}"
  type    = "{monitor_type}"
  message = <<-EOT
    {indent_message(full_message)}
  EOT

  query = "{escape_hcl_string(query)}"

  monitor_thresholds {{
{chr(10).join(thresholds_lines)}
  }}

  evaluation_delay    = {evaluation_delay}
  notify_no_data      = {notify_no_data}
  no_data_timeframe   = {no_data_timeframe}
  renotify_interval   = {renotify_interval}
  notify_audit        = {DEFAULT_NOTIFY_AUDIT}
  include_tags        = true

  tags = [
{tags_block}
  ]
}}
'''


def indent_message(message: str) -> str:
    """Re-indent a multi-line message so it sits cleanly inside the
    Terraform heredoc without breaking alignment."""
    lines = message.splitlines() or [""]
    return ("\n    ").join(lines)


def escape_hcl_string(value: str) -> str:
    return value.replace('"', '\\"')


def render_service_file(spec: dict) -> str:
    service = spec["service"]
    env = spec.get("env", "production")
    team = spec.get("team", "platform")
    notify = spec.get("notify", [])
    monitors = spec.get("monitors", [])

    if not monitors:
        raise ValueError(f"spec for '{service}' has no monitors defined")

    header = (
        f"# GENERATED FILE — do not hand-edit.\n"
        f"# Source spec: {service}.json\n"
        f"# Regenerate with: python3 datadog_monitor_gen.py specs/{service}.json\n"
        f"#\n"
        f"# Review thresholds and notification targets before applying.\n"
        f"# This file intentionally does not run `terraform apply` for you.\n\n"
    )

    blocks = [render_monitor(service, env, team, notify, m) for m in monitors]
    return header + "\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Datadog monitor Terraform from a JSON service spec.")
    parser.add_argument("spec", type=Path, help="Path to the service spec JSON file")
    parser.add_argument(
        "-o", "--out-dir", type=Path, default=Path("."),
        help="Directory to write the generated .tf file into (default: current directory)"
    )
    args = parser.parse_args(argv)

    try:
        spec = json.loads(args.spec.read_text())
    except FileNotFoundError:
        print(f"error: spec file not found: {args.spec}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error: {args.spec} is not valid JSON ({exc})", file=sys.stderr)
        return 1

    try:
        contents = render_service_file(spec)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{spec['service']}_monitors.tf"
    out_path.write_text(contents)

    monitor_count = len(spec.get("monitors", []))
    print(f"wrote {out_path} ({monitor_count} monitor{'s' if monitor_count != 1 else ''})")
    print("review thresholds + notification targets, then `terraform plan` as usual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
