# SLO Burn Rate Calculator

Know how fast you're burning through your error budget — before your SLO breaches.

Given your SLO target, window, and current error rate, this script calculates your burn rate, tells you exactly when your budget will exhaust, and classifies the situation using the Google SRE Workbook fast-burn / slow-burn model.

Supports single-service and multi-service modes. No external dependencies.

## Requirements

Python 3.10+ · No external dependencies (stdlib only)

## Usage

**Interactive mode:**
```bash
python slo_burn_rate.py
```

**Single service via env vars:**
```bash
export SLO_TARGET=99.9
export WINDOW_DAYS=30
export ERROR_RATE=2.0
export SERVICE=payment-api
python slo_burn_rate.py
```

**Multi-service mode:**
```bash
ERVICES='payment-api:99.9:2.0,auth-service:99.9:0.8,ride-dispatch:99.9:0.05' python slo_burn_rate.py
```

## Configuration

| Variable      | Default         | Description                                    |
|---------------|-----------------|--------------------------------------------------|
| `SLO_TARGET`  | (prompted)      | SLO target percentage, e.g. `99.9`              |
| `WINDOW_DAYS` | `30`            | SLO rolling window in days                      |
| `ERROR_RATE`  | `0`             | Current error rate percentage, e.g. `0.8`       |
| `SERVICE`     | `unnamed-service` | Service name label                             |
| `SERVICES`    | —               | Multi-service: `name:slo:error_rate[,...]`      |

## Sample Output

**Single service (fast burn):**
```
====================================================================
  SLO Burn Rate Report  ·  payment-api
====================================================================
  SLO target     : 99.9%   (30d window)
  Error budget   : 0.1000%  (43.2m of allowed downtime)
  Current error  : 2.0000%

  Burn rate      : 20.00x  [██████████████████████████████]
  Budget exhausts: 1d 12h

  Status         : ⚠  FAST BURN

  Recommendation : Page on-call immediately. At this rate you'll exhaust your entire
                   30d error budget in 1d 12h.

  Alert thresholds for this SLO:
    Page now (>= 14.4x)  : error rate > 1.44%
    Watch   (>= 6.0x)    : error rate > 0.60%
====================================================================
```

**Multi-service summary:**
```
================================================================================
  SLO Burn Rate — Multi-Service Summary
================================================================================
  Service                         SLO     Err%    Burn   Exhausts In  Status
  ---------------------------- ------  -------  ------  ------------  ------------
  payment-api                    99.9   2.0000   20.00        1d 12h  ⚠ FAST BURN
  auth-service                   99.9   0.8000    8.00        3d 18h  ! SLOW BURN
  ride-dispatch                  99.9   0.0500    0.50       60d 00h  ✓ ON TRACK

  3 services  ·  1 fast-burn  ·  1 slow-burn  ·  1 on track
================================================================================
```

## How It Works

**Burn rate** = `current_error_rate / error_budget_rate`

A burn rate of 1 means you're consuming the budget at exactly the allowed pace — you'd exhaust it precisely at the end of the window. A burn rate of 14.4 means you'd exhaust it in ~2 days for a 30-day window.

**Time to exhaustion** = `window_duration / burn_rate`

**Alert thresholds** (Google SRE Workbook):

| Severity   | Burn rate | Meaning                                      |
|------------|-----------|----------------------------------------------|
| Fast burn  | ≥ 14.4x   | Exhausts 2% of monthly budget in 1 hour — page now |
| Slow burn  | ≥ 6.0x    | Will breach SLO within the window — open a ticket  |
| On track   | < 6.0x    | Within acceptable range                      |

## Tips

- Pipe the output into a Slack message via a cron job for a daily budget health check
- Use `SERVICES=` mode to check all your critical services in one shot during an incident
- Combine with the [DataDog P99 script](../../datadog/top-p99-endpoints/) to correlate high latency with error budget burn
