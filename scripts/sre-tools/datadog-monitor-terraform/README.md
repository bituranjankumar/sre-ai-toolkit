# Datadog Monitor Terraform Generator

Generate `datadog_monitor` Terraform resource blocks from a small JSON
service spec — instead of copy-pasting an existing `monitors.tf`, renaming
the service, and hoping you didn't fat-finger a threshold or a tag.

## Why

Onboarding a new service's monitors usually goes: find a similar service's
`monitors.tf`, duplicate it, find-and-replace the service name, adjust a
threshold or two, ship it. We've had at least two incidents where a monitor
fired against the wrong service because a `service:` tag in a copy-pasted
query didn't get updated. This script removes that step — you describe the
service and its monitors once in JSON, and it emits consistent, reviewable
HCL with the defaults that are easy to forget (`evaluation_delay`,
`notify_no_data`, `renotify_interval`, tagging, notification routing).

It does **not** call the Datadog API and does **not** run
`terraform apply`. It only generates `.tf` files for you to review, diff,
and commit like any other change.

## Usage

```
python3 datadog_monitor_gen.py specs/rides-dispatch-svc.json -o generated/
```

```
wrote generated/rides-dispatch-svc_monitors.tf (3 monitors)
review thresholds + notification targets, then `terraform plan` as usual.
```

## Spec format

One JSON file per service. See [`specs/rides-dispatch-svc.json`](./specs/rides-dispatch-svc.json)
for a full example with three monitors (error rate, p99 latency, queue depth).

```json
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
      "message": "Error rate above 2% for 5 minutes. Check the dispatch matching queue first.",
      "critical": 0.02,
      "warning": 0.01,
      "evaluation_delay": 300
    }
  ]
}
```

Only `service`, `monitors[].name`, `monitors[].query`, and
`monitors[].critical` are required — everything else falls back to sane
defaults (`team: platform`, `env: production`, 60s evaluation delay,
`notify_no_data: false`, 60-minute renotify interval).

## Output

One `.tf` file per service (`<service>_monitors.tf`), with one
`datadog_monitor` resource block per entry in `monitors`. Each block gets:

- a consistent resource name and title (`[env] service — monitor name`)
- the notification channels appended to the message body in Datadog's
  `@`-mention format
- standard tags: `service:`, `env:`, `team:`, `managed-by:terraform`
- the alerting defaults that tend to get forgotten in hand-written HCL

Generated files start with a header pointing back at the source spec and the
regeneration command, and are meant to be reviewed and diffed like any other
Terraform change — not applied blindly.

## Limitations

- No Datadog API calls — it won't validate that your query syntax is correct
  against live data. Run `terraform plan` and sanity-check the query in the
  Datadog UI before applying.
- Only `metric alert`-style monitors have been exercised in production; other
  monitor types (anomaly, composite, log alert) will generate but should get
  extra scrutiny on the threshold block shape.
