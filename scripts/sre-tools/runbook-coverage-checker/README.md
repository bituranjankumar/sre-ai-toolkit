# Runbook Coverage Checker

Scan an alert inventory and report which alerts have no linked runbook —
before an incident (or an AI incident-response tool) makes the gap obvious.

## Why

We wired up an AI incident-response tool to our alert pipeline. It kept
surfacing "no runbook found" for roughly half our services. Turns out we had
26 alert rules that had never had a runbook written for them, some going back
two years. Nobody noticed because the alerts still fired and someone always
figured it out on the call. The AI agent just made the gap impossible to ignore.

This script takes an alert inventory (JSON) and a runbooks directory and
produces a coverage report: which alerts are covered, which aren't, coverage
percent by team, and an uncovered list sorted by severity so you know where to
start filling the gaps.

## Usage

```
python3 runbook_coverage_checker.py specs/alerts.json --runbooks-dir ./runbooks
```

```
RUNBOOK COVERAGE REPORT
==================================================
Total alerts : 14
Covered      : 6  (42%)
Uncovered    : 8

UNCOVERED ALERTS
--------------------------------------------------

  CRITICAL
    EtcdDiskLatencyHigh                 platform-engineering
    PaymentGatewayTimeout               payments-platform

  WARNING
    DriverMatchingQueueDepthHigh        mobility-platform
    DriverOnboardingJobFailed           driver-experience
    GRPCErrorBudgetBurning              mobility-platform
    HorizontalPodAutoscalerMaxed        platform-engineering
    IngressCertExpirySoon               platform-engineering
    RedisEvictionRateHigh               data-platform

BY TEAM
--------------------------------------------------
  Team                      Total  Covered   Coverage
  driver-experience             1        0         0%  [..........]
  mobility-platform             3        1        33%  [###.......]
  data-platform                 2        1        50%  [#####.....]
  payments-platform             2        1        50%  [#####.....]
  platform-engineering          6        3        50%  [#####.....]
```

Exit code is `1` if any alerts are uncovered, `0` if all have coverage — pipe
it straight into CI to gate a deploy or post a Slack summary:

```
python3 runbook_coverage_checker.py alerts.json --runbooks-dir ./runbooks \
  || notify_oncall.sh "runbook gaps detected — see report"
```

Filter to a single team (useful for team-specific CI jobs or PR checks):

```
python3 runbook_coverage_checker.py alerts.json --runbooks-dir ./runbooks \
  --team platform-engineering
```

Machine-readable JSON output for alerting pipelines or dashboards:

```
python3 runbook_coverage_checker.py alerts.json --runbooks-dir ./runbooks --json
```

## Alert inventory format

One JSON array, one entry per alert. See
[`specs/mobility-platform-alerts.json`](./specs/mobility-platform-alerts.json)
for a full example.

```json
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
```

Fields:

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Alert rule name, must be unique across the inventory |
| `severity` | yes | `critical`, `warning`, or `info` |
| `team` | yes | Owning team — drives the by-team breakdown |
| `runbook_url` | no | If present and non-empty, the alert is immediately considered covered |

YAML inventories are also supported if PyYAML is installed (`pip install pyyaml`).

## What counts as covered

An alert is covered if **either**:

1. It has a non-empty `runbook_url` in the inventory (covers wiki links, Notion
   pages, Confluence docs — anything with a URL), **or**
2. A file exists in the runbooks directory whose name matches the normalised
   alert name — case-insensitive, with camelCase split and underscores/spaces
   converted to hyphens.

Name normalisation examples:

| Alert name | Matches file |
|---|---|
| `KafkaConsumerLagHigh` | `kafka-consumer-lag-high.md` |
| `pod_crash_loop_backoff` | `pod-crash-loop-backoff.md` |
| `Payments Gateway Timeout` | `payments-gateway-timeout.md` |

Any file extension is accepted — `.md`, `.html`, `.txt`, `.pdf`.

## Limitations

- Only checks for existence of a runbook, not its quality or whether it's
  up to date. A one-line placeholder file counts as "covered."
- Runbook matching is by filename only — it doesn't follow `runbook_url` links
  to verify the page actually exists or is accessible.
- The inventory is a flat list; it doesn't parse Prometheus/Alertmanager YAML
  natively. Export your alert rules to JSON (or install PyYAML for YAML support)
  before running.
