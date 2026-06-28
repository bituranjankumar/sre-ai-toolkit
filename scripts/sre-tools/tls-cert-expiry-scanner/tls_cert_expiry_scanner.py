#!/usr/bin/env python3
"""
tls_cert_expiry_scanner.py

Scan a list of services for TLS certificate expiry and flag anything
inside a warning/critical window, instead of finding out a cert expired
because customers started seeing SSL errors in production.

Why this exists
----------------
We've had at least one outage where an internal service's cert expired
on a Saturday and nobody noticed until the mTLS handshake started failing
between gateway and dispatch. Cert expiry is one of the most predictable
failure modes in the entire stack -- the expiry date is known the moment
the cert is issued -- and yet it keeps catching teams off guard because
nothing proactively watches it across the fleet.

This script connects to each service in a small JSON inventory, performs
a real TLS handshake, reads the leaf certificate's notAfter date, and
reports days-until-expiry with CRITICAL/WARNING/OK status per service.
It is meant to run on a schedule (cron, a CI pipeline, a scheduled
GitHub Action) and exit non-zero when anything is CRITICAL, so it can
gate a pipeline or trigger a page on its own.

It does NOT renew certificates and does NOT touch your cert management
system (cert-manager, ACM, Vault PKI, etc.) -- it only reports what it
sees on the wire, the same view your customers' clients would get.

Usage
-----
    python3 tls_cert_expiry_scanner.py services.json
    python3 tls_cert_expiry_scanner.py services.json --warning-days 21 --critical-days 7
    python3 tls_cert_expiry_scanner.py services.json --json > cert_status.json

Inventory format (JSON)
------------------------
[
  {"name": "rides-dispatch-svc", "host": "dispatch.internal.grab-mobility.com", "port": 443, "team": "mobility-platform"},
  {"name": "payments-gateway", "host": "payments-gw.internal.grab-mobility.com", "port": 8443, "team": "payments-platform", "critical_days": 3}
]

Only "name" and "host" are required. "port" defaults to 443. Per-service
"warning_days" / "critical_days" override the global --warning-days /
--critical-days flags, for services that need a tighter window (e.g. a
gateway with a slow, manual cert rotation process).

Output
------
A status table to stdout, one row per service, sorted by days remaining
(most urgent first). Exit code is 2 if any service is CRITICAL or could
not be checked, 1 if any service is WARNING, 0 otherwise -- so this can
gate a CI job or a deploy pipeline directly.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PORT = 443
DEFAULT_WARNING_DAYS = 30
DEFAULT_CRITICAL_DAYS = 14
DEFAULT_TIMEOUT_SECONDS = 5

# OpenSSL's getpeercert() returns notAfter in this exact strftime format,
# e.g. "Aug  4 23:59:59 2026 GMT". Don't be tempted to use isoformat parsing.
CERT_DATE_FORMAT = "%b %d %H:%M:%S %Y %Z"


class CheckResult:
    def __init__(self, name, host, port, team, status, days_remaining=None, expires_on=None, error=None):
        self.name = name
        self.host = host
        self.port = port
        self.team = team
        self.status = status  # "OK" | "WARNING" | "CRITICAL" | "ERROR"
        self.days_remaining = days_remaining
        self.expires_on = expires_on
        self.error = error

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "team": self.team,
            "status": self.status,
            "days_remaining": self.days_remaining,
            "expires_on": self.expires_on,
            "error": self.error,
        }


def fetch_cert_expiry(host: str, port: int, timeout: int) -> datetime:
    """Open a real TLS connection and read the leaf cert's notAfter date.

    Deliberately does NOT disable cert verification -- if the chain is
    broken or the hostname doesn't match, that's worth surfacing too,
    not papering over."""
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls_sock:
            cert = tls_sock.getpeercert()
    not_after = cert.get("notAfter")
    if not not_after:
        raise ValueError("certificate has no notAfter field")
    return datetime.strptime(not_after, CERT_DATE_FORMAT).replace(tzinfo=timezone.utc)


def classify(days_remaining: int, warning_days: int, critical_days: int) -> str:
    if days_remaining < 0:
        return "CRITICAL"  # already expired
    if days_remaining <= critical_days:
        return "CRITICAL"
    if days_remaining <= warning_days:
        return "WARNING"
    return "OK"


def check_service(spec: dict, default_warning_days: int, default_critical_days: int, timeout: int) -> CheckResult:
    name = spec["name"]
    host = spec["host"]
    port = spec.get("port", DEFAULT_PORT)
    team = spec.get("team", "unassigned")
    warning_days = spec.get("warning_days", default_warning_days)
    critical_days = spec.get("critical_days", default_critical_days)

    try:
        expiry = fetch_cert_expiry(host, port, timeout)
    except (socket.timeout, socket.gaierror, ConnectionRefusedError, ssl.SSLError, ValueError, OSError) as exc:
        return CheckResult(name, host, port, team, "ERROR", error=f"{type(exc).__name_]}: {exc}")

    days_remaining = (expiry - datetime.now(timezone.utc)).days
    status = classify(days_remaining, warning_days, critical_days)
    return CheckResult(name, host, port, team, status, days_remaining, expiry.strftime("%Y-%m-%d"))


def render_table(results: list[CheckResult]) -> str:
    order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "OK": 3}
    rows = sorted(results, key=lambda r: (order[r.status], r.days_remaining if r.days_remaining is not None else -1))

    header = f"{'STATUS':<9} {'SERVICE':<28} {'TEAM':<20} {'EXPIRES':<12} {'DAYS LEFT':<10} DETAIL"
    lines = [header, "-" * len(header)]
    for r in rows:
        days = str(r.days_remaining) if r.days_remaining is not None else "-"
        expires = r.expires_on or "-"
        detail = r.error or ""
        lines.append(f"{r.status:<9} {r.name:<28} {r.team:<20} {expires:<12} {days:<10} {detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan services for TLS certificate expiry.")
    parser.add_argument("inventory", type=Path, help="Path to the JSON service inventory")
    parser.add_argument("--warning-days", type=int, default=DEFAULT_WARNING_DAYS,
                         help=f"Default warning threshold in days (default: {DEFAULT_WARNING_DAYS})")
    parser.add_argument("--critical-days", type=int, default=DEFAULT_CRITICAL_DAYS,
                         help=f"Default critical threshold in days (default: {DEFAULT_CRITICAL_DAYS})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                         help=f"Per-connection timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = parser.parse_args(argv)

    try:
        specs = json.loads(args.inventory.read_text())
    except FileNotFoundError:
        print(f"error: inventory file not found: {args.inventory}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: {args.inventory} is not valid JSON ({exc})", file=sys.stderr)
        return 2

    results = [check_service(spec, args.warning_days, args.critical_days, args.timeout) for spec in specs]

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(render_table(results))

    if any(r.status in ("CRITICAL", "ERROR") for r in results):
        return 2
    if any(r.status == "WARNING" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
