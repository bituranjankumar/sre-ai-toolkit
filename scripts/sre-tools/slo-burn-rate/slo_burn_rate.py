#!/usr/bin/env python3
"""
slo_burn_rate.py
================
SLO burn rate calculator for SRE on-call and incident triage.

Given your SLO window, error budget, and current error rate, this script tells
you how fast you're burning through your error budget, when you'll exhaust it,
and whether you're in a fast-burn (page now) or slow-burn (watch carefully)
scenario — using the same burn rate model described in the Google SRE workbook.

Usage:
    python slo_burn_rate.py

    # Or pass everything via env vars:
    SLO_TARGET=99.9 WINDOW_DAYS=30 ERROR_RATE=0.5 python slo_burn_rate.py

    # Multi-service mode (comma-separated):
    SERVICES='payment-api:99.9:0.8,auth-service:99.95:0.3' python slo_burn_rate.py

Concepts:
    Error budget   = 1 - SLO target  (e.g. 99.9% SLO → 0.1% budget)
    Burn rate      = actual error rate / error budget rate
                     burn rate of 1 = exactly consuming budget at SLO pace
                     burn rate of 2 = consuming budget 2x faster than allowed
    Exhaustion     = time until 100% of error budget is consumed at current rate

Alert thresholds (Google SRE Workbook defaults):
    Fast burn  : burn rate >= 14.4  → page immediately (2% budget in 1h)
    Slow burn  : burn rate >= 6     → ticket / watch closely
    On track   : burn rate < 6      → within acceptable range
"""

import os
import sys
import math
from dataclasses import dataclass, field
from datetime import timedelta


# ── Constants ────────────────────────────────────────────────────────────────

FAST_BURN_THRESHOLD = 14.4   # exhausts 2% of 30d budget in 1 hour
SLOW_BURN_THRESHOLD = 6.0    # exhausts budget ~5x faster than allowed
HOURS_IN_DAY        = 24
MINUTES_IN_HOUR     = 60


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class SLOConfig:
    service:      str
    slo_pct:      float          # e.g. 99.9
    window_days:  int            # e.g. 30
    error_rate:   float          # current % error rate, e.g. 0.5


@dataclass
class BurnResult:
    config:            SLOConfig
    error_budget_pct:  float     # e.g. 0.1 (%)
    error_budget_mins: float     # total allowed downtime in minutes
    burn_rate:         float     # dimensionless multiplier
    budget_consumed_pct: float   # how much of budget is already gone (if tracking since window start)
    time_to_exhaustion: float    # minutes until budget hits 0 at current burn rate
    severity:          str       # FAST_BURN | SLOW_BURN | ON_TRACK
    recommendation:    str


# ── Core maths ───────────────────────────────────────────────────────────────

def calculate(cfg: SLOConfig) -> BurnResult:
    error_budget_pct   = round(100.0 - cfg.slo_pct, 6)          # e.g. 0.1
    window_mins        = cfg.window_days * HOURS_IN_DAY * MINUTES_IN_HOUR
    error_budget_mins  = window_mins * (error_budget_pct / 100)  # allowed bad minutes

    # Burn rate: how many times faster than "just acceptable" we're consuming budget.
    # At burn_rate=1 we exhaust budget in exactly window_days.
    if error_budget_pct <= 0:
        raise ValueError(f"SLO target {cfg.slo_pct}% leaves no error budget.")

    burn_rate = cfg.error_rate / error_budget_pct

    # Time to exhaustion: calendar time until budget hits 0 at the current burn rate.
    # At burn_rate=1, this equals the full window. At burn_rate=5, window/5.
    if cfg.error_rate <= 0:
        time_to_exhaustion = float("inf")
    else:
        time_to_exhaustion = window_mins / burn_rate

    # Severity classification
    if burn_rate >= FAST_BURN_THRESHOLD:
        severity = "FAST_BURN"
        recommendation = (
            f"Page on-call immediately. At this rate you'll exhaust your entire "
            f"{cfg.window_days}d error budget in {fmt_duration(time_to_exhaustion)}. "
            f"This is the Google SRE Workbook 'page now' threshold (burn rate >= {FAST_BURN_THRESHOLD})."
        )
    elif burn_rate >= SLOW_BURN_THRESHOLD:
        severity = "SLOW_BURN"
        recommendation = (
            f"Create a ticket and monitor closely. Budget exhaustion in "
            f"{fmt_duration(time_to_exhaustion)} if rate holds. "
            f"Not page-worthy yet but will breach SLO within the window."
        )
    else:
        severity = "ON_TRACK"
        recommendation = (
            f"Within acceptable range. At this burn rate, budget exhausts in "
            f"{fmt_duration(time_to_exhaustion)} — safely within your {cfg.window_days}d window "
            f"({fmt_duration(window_mins)} total). No immediate action needed."
        )

    return BurnResult(
        config=cfg,
        error_budget_pct=error_budget_pct,
        error_budget_mins=error_budget_mins,
        burn_rate=round(burn_rate, 2),
        budget_consumed_pct=0.0,   # would need start-of-window baseline to compute
        time_to_exhaustion=time_to_exhaustion,
        severity=severity,
        recommendation=recommendation,
    )


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt_duration(minutes: float) -> str:
    if minutes == float("inf"):
        return "∞ (no errors)"
    if minutes < 1:
        return f"{minutes * 60:.0f}s"
    if minutes < 60:
        return f"{minutes:.1f}m"
    if minutes < HOURS_IN_DAY * 60:
        h = int(minutes // 60)
        m = int(minutes % 60)
        return f"{h}h {m:02d}m"
    days  = int(minutes // (HOURS_IN_DAY * 60))
    hours = int((minutes % (HOURS_IN_DAY * 60)) // 60)
    return f"{days}d {hours:02d}h"


def severity_colour(severity: str) -> str:
    return {"FAST_BURN": "⚠  FAST BURN", "SLOW_BURN": "!  SLOW BURN", "ON_TRACK": "✓  ON TRACK"}[severity]


def burn_bar(burn_rate: float, max_rate: float = 20.0, width: int = 30) -> str:
    filled = min(int((burn_rate / max_rate) * width), width)
    bar    = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"


# ── Output ────────────────────────────────────────────────────────────────────

def print_single(r: BurnResult) -> None:
    c = r.config
    print()
    print("=" * 68)
    print(f"  SLO Burn Rate Report  ·  {c.service}")
    print("=" * 68)
    print(f"  SLO target     : {c.slo_pct}%   ({c.window_days}d window)")
    print(f"  Error budget   : {r.error_budget_pct:.4f}%  ({fmt_duration(r.error_budget_mins)} of allowed downtime)")
    print(f"  Current error  : {c.error_rate:.4f}%")
    print()
    print(f"  Burn rate      : {r.burn_rate:.2f}x  {burn_bar(r.burn_rate)}")
    print(f"  Budget exhausts: {fmt_duration(r.time_to_exhaustion)}")
    print()
    print(f"  Status         : {severity_colour(r.severity)}")
    print()
    print(f"  Recommendation : {r.recommendation}")
    print()
    _print_thresholds(r.error_budget_pct)
    print("=" * 68)
    print()


def _print_thresholds(budget_pct: float) -> None:
    fast_rate = round(FAST_BURN_THRESHOLD * budget_pct, 4)
    slow_rate = round(SLOW_BURN_THRESHOLD * budget_pct, 4)
    print(f"  Alert thresholds for this SLO:")
    print(f"    Page now (>= {FAST_BURN_THRESHOLD}x)  : error rate > {fast_rate}%")
    print(f"    Watch   (>= {SLOW_BURN_THRESHOLD}x)    : error rate > {slow_rate}%")


def print_multi(results: list[BurnResult]) -> None:
    print()
    print("=" * 80)
    print("  SLO Burn Rate — Multi-Service Summary")
    print("=" * 80)
    hdr = f"  {'Service':<28} {'SLO':>6}  {'Err%':>7}  {'Burn':>6}  {'Exhausts In':>12}  Status"
    sep = f"  {'-'*28} {'-'*6}  {'-'*7}  {'-'*6}  {'-'*12}  {'-'*12}"
    print(hdr)
    print(sep)
    for r in sorted(results, key=lambda x: x.burn_rate, reverse=True):
        c = r.config
        name = c.service[:27]
        status = {"FAST_BURN": "⚠ FAST BURN", "SLOW_BURN": "! SLOW BURN", "ON_TRACK": "✓ ON TRACK"}[r.severity]
        print(
            f"  {name:<28} {c.slo_pct:>6}  {c.error_rate:>7.4f}  "
            f"{r.burn_rate:>6.2f}  {fmt_duration(r.time_to_exhaustion):>12}  {status}"
        )
    print()
    fast = sum(1 for r in results if r.severity == "FAST_BURN")
    slow = sum(1 for r in results if r.severity == "SLOW_BURN")
    ok   = sum(1 for r in results if r.severity == "ON_TRACK")
    print(f"  {len(results)} services  ·  {fast} fast-burn  ·  {slow} slow-burn  ·  {ok} on track")
    print("=" * 80)
    print()


# ── Config / entrypoint ───────────────────────────────────────────────────────

def parse_services_env(raw: str) -> list[SLOConfig]:
    """Parse SERVICES='name:slo_pct:error_rate[,...]'"""
    configs = []
    for entry in raw.split(","):
        parts = entry.strip().split(":")
        if len(parts) != 3:
            print(f"ERROR: SERVICES entry '{entry}' must be name:slo_pct:error_rate")
            sys.exit(1)
        name, slo, err = parts
        configs.append(SLOConfig(
            service=name.strip(),
            slo_pct=float(slo),
            window_days=int(os.environ.get("WINDOW_DAYS", "30")),
            error_rate=float(err),
        ))
    return configs


def interactive_prompt() -> SLOConfig:
    print("\n  SLO Burn Rate Calculator")
    print("  ─────────────────────────")
    service     = input("  Service name      : ").strip() or "my-service"
    slo_pct     = float(input("  SLO target (%)    [99.9]  : ").strip() or "99.9")
    window_days = int(input("  SLO window (days) [30]    : ").strip() or "30")
    error_rate  = float(input("  Current error (%) [0.0]   : ").strip() or "0.0")
    return SLOConfig(service=service, slo_pct=slo_pct,
                     window_days=window_days, error_rate=error_rate)


def main():
    services_raw = os.environ.get("SERVICES", "")

    if services_raw:
        # Multi-service mode
        configs = parse_services_env(services_raw)
        results = [calculate(cfg) for cfg in configs]
        print_multi(results)
        # Print detail for any fast/slow burns
        for r in results:
            if r.severity != "ON_TRACK":
                print_single(r)

    elif os.environ.get("SLO_TARGET"):
        # Single-service env-var mode
        cfg = SLOConfig(
            service=os.environ.get("SERVICE", "unnamed-service"),
            slo_pct=float(os.environ["SLO_TARGET"]),
            window_days=int(os.environ.get("WINDOW_DAYS", "30")),
            error_rate=float(os.environ.get("ERROR_RATE", "0")),
        )
        print_single(calculate(cfg))

    else:
        # Interactive mode
        try:
            cfg    = interactive_prompt()
            result = calculate(cfg)
            print_single(result)
        except KeyboardInterrupt:
            print("\n  Aborted.")
            sys.exit(0)
        except ValueError as e:
            print(f"\n  ERROR: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
