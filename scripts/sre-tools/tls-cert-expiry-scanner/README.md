# TLS Cert Expiry Scanner

Scan a list of services for TLS certificate expiry and flag anything inside a
warning/critical window — instead of finding out a cert expired because
customers started seeing SSL errors in production.

## Why

We've had an outage where an internal service's cert expired on a Saturday
and nobody noticed until the mTLS handshake between gateway and dispatch
started failing. Cert expiry is one of the most predictable failure modes in
the entire stack — the expiry date is fixed the moment the cert is issued —
and it still keeps catching teams off guard because nothing is proactively
watching it across the fleet.

This script connects to each service in a small JSON inventory, performs a
real TLS handshake, reads the leaf certificate's `notAfter` date, and reports
days-until-expiry with `CRITICAL` / `WARNING` / `OK` status per service. It's
meant to run on a schedule (cron, a scheduled CI job, a GitHub Action) and
exit non-zero when something needs attention, so it can gate a pipeline or
trigger a page on its own.

It does **not** renew certificates and does **not** touch your cert
management system (cert-manager, ACM, Vault PKI, etc.) — it only reports what
it sees on the wire, the same view a real client connection would get.

## Usage

```
python3 tls_cert_expiry_scanner.py specs/mobility-platform-services.json
```

```
STATUS    SERVICE                      TEAM                 EXPIRES      DAYS LEFT  DETAIL
------------------------------------------------------------------------------------------
CRITICAL  payments-gateway             payments-platform    2026-07-03   5
WARNING   rides-dispatch-svc           mobility-platform    2026-07-20   22
OK        driver-matching-api          mobility-platform    2026-09-12   75
OK        driver-onboarding-portal     driver-experience     2026-10-01   94
ERROR     legacy-fare-calculator       mobility-platform    -            -          SSLCertVerificationError: hostname mismatch
```

Exit code is `2` if anything is `CRITICAL` or `ERROR` (couldn't be checked at
all), `1` if anything is `WARNING`, `0` otherwise — wire this straight into a
CI job or a scheduled pipeline step:

```
python3 tls_cert_expiry_scanner.py specs/mobility-platform-services.json || page_oncall.sh "cert expiry check failed"
```

For machine consumption (alerting pipelines, dashboards):

```
python3 tls_cert_expiry_scanner.py specs/mobility-platform-services.json --json
```

## Inventory format

One JSON array, one entry per service. See
[`specs/mobility-platform-services.json`](./specs/mobility-platform-services.json)
for a full example.

```json
{
  "name": "payments-gateway",
  "host": "payments-gw.internal.grab-mobility.com",
  "port": 8443,
  "team": "payments-platform",
  "critical_days": 5
}
```

Only `name` and `host` are required — `port` defaults to `443`.
`warning_days` / `critical_days` override the global `--warning-days` /
`--critical-days` flags per service, for anything that needs a tighter
window (a gateway with a slow, manual rotation process) or a looser one
(something already on automated ACME renewal).

## Output

A status table sorted most-urgent-first (`CRITICAL` → `ERROR` → `WARNING` →
`OK`), or a JSON array with the `--json` flag. Each entry includes the
service name, team, computed expiry date, days remaining, and — for
connection or verification failures — the underlying error so you know
whether it's actually an expiring cert or a network/DNS/cert-chain problem
that needs different attention.

## Limitations

- Only checks the leaf certificate seen at connection time — it doesn't
  evaluate the full chain's validity beyond what `ssl.create_default_context()`
  already verifies, and it doesn't check OCSP/CRL revocation status.
- Verification is **not** disabled — a broken chain or hostname mismatch
  shows up as an `ERROR` row, not silently ignored. That's deliberate, but
  it does mean this script alone won't tell you whether the *content* of a
  cert (SANs, key usage) matches what you expect — only whether it's
  currently valid and how long it has left.
- Network checks only — doesn't read from your CA / cert-manager API, so it
  won't catch a renewal that already happened in storage but hasn't been
  deployed to the service yet (which is, in fact, its own common failure
  mode worth watching for separately).
