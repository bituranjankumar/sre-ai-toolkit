#!/usr/bin/env python3
"""
dd_top_p99_endpoints.py
========================
Fetch the top N P99 (99th percentile) latency endpoints from Datadog
for a configurable time window and print a ranked, visual summary.

Real-world use case: When an alert fires, answer "which endpoint is the
slowest right now?" in seconds from your terminal — no dashboard clicking.

Usage:
    export DD_API_KEY=<your_api_key>
    export DD_APP_KEY=<your_app_key>
    python dd_top_p99_endpoints.py

Optional env vars:
    DD_SITE        Datadog site (default: datadoghq.com)
    TIME_WINDOW    Lookback in hours (default: 1)
    TOP_N          Number of endpoints to return (default: 10)
    SERVICE        Filter by a specific service name (default: all)
    ENV            Filter by environment tag e.g. production (default: all)
    EXPORT_JSON    Set to 'true' to export results to JSON (default: false)
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone

try:
    from datadog_api_client import ApiClient, Configuration
    from datadog_api_client.v1.api.metrics_api import MetricsApi
except ImportError:
    print("ERROR: Install dependencies first: pip install -r requirements.txt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_config() -> dict:
    """Read and validate configuration from environment variables."""
    api_key = os.environ.get("DD_API_KEY", "")
    app_key = os.environ.get("DD_APP_KEY", "")
    if not api_key or not app_key:
        print("ERROR: DD_API_KEY and DD_APP_KEY environment variables are required.")
        print("       Get them from: Datadog -> Organization Settings -> API/App Keys")
        sys.exit(1)

    return {
        "api_key": api_key,
        "app_key": app_key,
        "site": os.environ.get("DD_SITE", "datadoghq.com"),
        "time_window": int(os.environ.get("TIME_WINDOW", "1")),
        "top_n": int(os.environ.get("TOP_N", "10")),
        "service": os.environ.get("SERVICE", ""),
        "env": os.environ.get("ENV", ""),
        "export_json": os.environ.get("EXPORT_JSON", "false").lower() == "true",
    }


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

def build_query(cfg: dict) -> str:
    """Build the Datadog metrics query for P99 latency by resource/endpoint."""
    filters = []
    if cfg["service"]:
        filters.append(f"service:{cfg['service']}")
    if cfg["env"]:
        filters.append(f"env:{cfg['env']}")

    filter_str = ",".join(filters) if filters else "*"
    top_n = cfg["top_n"]

    # Uses trace.web.request for HTTP endpoints (works with Datadog APM).
    # Falls back gracefully if you use trace.servlet.request or similar.
    return (
        f"top(p99:trace.web.request{{{filter_str}}} by {{resource_name}},"
        f"{top_n},'max','desc')"
    )


# ---------------------------------------------------------------------------
# Fetch from Datadog
# ---------------------------------------------------------------------------

def fetch_p99_endpoints(cfg: dict) -> list:
    """Query Datadog Metrics API v1 for top P99 latency endpoints."""
    configuration = Configuration()
    configuration.api_key["apiKeyAuth"] = cfg["api_key"]
    configuration.api_key["appKeyAuth"] = cfg["app_key"]
    configuration.server_variables["site"] = cfg["site"]

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=cfg["time_window"])
    query = build_query(cfg)

    print(f"  Querying Datadog ({cfg['site']}) for last {cfg['time_window']}h ...")
    print(f"  Query: {query}\n")

    with ApiClient(configuration) as api_client:
        api = MetricsApi(api_client)
        response = api.query_metrics(
            _from=int(start.timestamp()),
            to=int(now.timestamp()),
            query=query,
        )

    results = []
    if not response.series:
        return results

    for series in response.series:
        # Extract endpoint name from scope tag
        scope = series.scope or ""
        endpoint = scope.replace("resource_name:", "").strip()
        if not endpoint:
            endpoint = "unknown"

        # Collect all non-null data points; values are in nanoseconds
        points = [
            p[1] for p in (series.pointlist or [])
            if p[1] is not None
        ]
        if not points:
            continue

        max_p99_ns = max(points)
        max_p99_ms = max_p99_ns / 1_000_000  # nanoseconds -> milliseconds

        results.append({
            "endpoint": endpoint,
            "p99_ms": round(max_p99_ms, 2),
            "sample_count": len(points),
        })

    # Sort descending by P99 latency
    results.sort(key=lambda x: x["p99_ms"], reverse=True)
    return results[: cfg["top_n"]]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(results: list, cfg: dict) -> None:
    """Print a ranked, visual table of P99 endpoints."""
    service_label = f"service={cfg['service']}" if cfg["service"] else "all services"
    env_label = f", env={cfg['env']}" if cfg["env"] else ""
    header = (
        f"Top {cfg['top_n']} P99 Endpoints"
        f" — last {cfg['time_window']}h"
        f" ({service_label}{env_label})"
    )

    print("=" * 72)
    print(f"  {header}")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    if not results:
        print("\n  No data found. Check your API keys, time window, and service name.")
        print("  Tip: Make sure Datadog APM is enabled for your services.\n")
        return

    print(f"\n  {'Rank':<5} {'P99 ms':<14} {'Endpoint'}")
    print(f"  {'-'*5} {'-'*14} {'-'*48}")

    max_p99 = results[0]["p99_ms"] if results else 1

    for i, row in enumerate(results, 1):
        bar_len = int((row["p99_ms"] / max_p99) * 30)
        bar = "█" * bar_len
        latency_color = ""
        if row["p99_ms"] > 1000:
            latency_color = " [!!! >1s]"
        elif row["p99_ms"] > 500:
            latency_color = " [!! >500ms]"
        elif row["p99_ms"] > 200:
            latency_color = " [! >200ms]"

        print(f"  {i:<5} {row['p99_ms']:<14.2f} {row['endpoint']}{latency_color}")
        print(f"        {bar}")

    print()


def export_json(results: list, cfg: dict) -> None:
    """Export results to a timestamped JSON file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"p99_report_{timestamp}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "time_window_hours": cfg["time_window"],
        "service_filter": cfg["service"] or "all",
        "env_filter": cfg["env"] or "all",
        "top_n": cfg["top_n"],
        "results": results,
    }
    with open(filename, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"  JSON report saved -> {filename}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = get_config()
    results = fetch_p99_endpoints(cfg)
    print_report(results, cfg)
    if cfg["export_json"]:
        export_json(results, cfg)
