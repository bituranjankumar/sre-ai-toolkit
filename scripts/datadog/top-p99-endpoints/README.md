# DataDog Top P99 Endpoints

A Python script that queries the **DataDog Metrics API** and surfaces your top N slowest P99 latency endpoints in real-time — ranked, visually scored, and optionally exported to JSON.

Built from real-world SRE experience: automating P99 latency tracking to accelerate incident resolution for high-traffic services.

---

## Why this exists

When an alert fires, the first question is always:
> *"Which endpoint is the slowest right now?"*

Instead of clicking through dashboards, this script gives you the answer in seconds — right from your terminal.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export DD_API_KEY=<your_datadog_api_key>
export DD_APP_KEY=<your_datadog_app_key>
```

> Get keys from: **Datadog → Organization Settings → API Keys / Application Keys**

### 3. Run

```bash
python dd_top_p99_endpoints.py
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DD_API_KEY` | *(required)* | Datadog API key |
| `DD_APP_KEY` | *(required)* | Datadog Application key |
| `DD_SITE` | `datadoghq.com` | Use `datadoghq.eu` for EU region |
| `TIME_WINDOW` | `1` | Lookback window in hours |
| `TOP_N` | `10` | Number of endpoints to return |
| `SERVICE` | *(all)* | Filter by service name e.g. `payment-service` |
| `ENV` | *(all)* | Filter by environment e.g. `production` |
| `EXPORT_JSON` | `false` | Set to `true` to save results as JSON |

---

## Example Output

```
========================================================================
  Top 10 P99 Endpoints — last 1h (all services)
  Generated: 2026-05-01 08:42 UTC
========================================================================

  Rank  P99 ms         Endpoint
  ----- -------------- ------------------------------------------------
  1     1843.20        POST /api/v2/payments/process [!!! >1s]
        ██████████████████████████████
  2     920.50         GET /api/v1/orders/{id}/history [!! >500ms]
        ███████████████
  3     541.30         PUT /api/v2/users/{id}/profile [!! >500ms]
        █████████
  4     198.70         GET /api/v1/rides/estimate
        ███
```

---

## How to get your Datadog keys

1. Go to **Datadog → Organization Settings → API Keys** → Create or copy a key
2. Go to **Organization Settings → Application Keys** → Create a key with `metrics_read` scope

---

## Ideas to extend this script

- Add **Slack/PagerDuty alerting** when a threshold is breached
- Schedule it via cron or a GitHub Action for daily reports
- Compare P99 across two time windows (before/after deploy)
- Add a `--watch` mode that refreshes every 60 seconds

---

Built by [@bituranjankumar](https://github.com/bituranjankumar) | [LinkedIn](https://www.linkedin.com/in/b-ranjan-kumar)
