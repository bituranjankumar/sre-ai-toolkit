# 🛠️ SRE AI Toolkit

A growing collection of scripts, tools, and real-world SRE/DevOps solutions — built by a Senior SRE with 11+ years of experience.

**Goal:** Help SRE, DevOps, and platform engineers solve real problems faster with practical scripts and AI-augmented tooling.

---

## 📂 Repository Structure

\`\`\`
sre-ai-toolkit/
├── scripts/
│   ├── datadog/          # DataDog automation scripts
│   ├── github-actions/   # GitHub Actions analysis scripts
│   └── sre-tools/        # SRE observability and reliability tools
└── linkedin-posts/       # Source content for LinkedIn posts
\`\`\`

## 🗂️ Scripts

| Script | Description |
|--------|-------------|
| [DataDog Top P99 Endpoints](./scripts/datadog/top-p99-endpoints/) | Fetch the top 10 slowest P99 latency endpoints from the DataDog API |
| [GitHub Actions Slow Workflow Analyser](./scripts/github-actions/slow-workflows/) | Surface your top N slowest GitHub Actions workflows with P95/P99 stats — great for DORA analysis |
| [GitHub Actions CI Regression Detector](./scripts/github-actions/ci-regression-detector/) | Compare workflow durations before vs after a deploy — flags regressions and improvements with avg/P95/P99 delta |
| [SLO Burn Rate Calculator](./scripts/sre-tools/slo-burn-rate/) | Calculate your error budget burn rate and time-to-exhaustion — fast/slow burn classification per the Google SRE Workbook |
| [Datadog Monitor Terraform Generator](./scripts/sre-tools/datadog-monitor-terraform/) | Generate `datadog_monitor` Terraform resource blocks from a small JSON service spec — consistent naming, tags, and alerting defaults instead of copy-paste HCL |
| [TLS Cert Expiry Scanner](./scripts/sre-tools/tls-cert-expiry-scanner/) | Scan a list of services for TLS certificate expiry via a real handshake — flags anything inside a warning/critical window before customers see SSL errors |

---

## 🙋 About

Built by **Ranjan Kumar B** — Senior SRE at Grab, Kuala Lumpur.

- 🔗 [LinkedIn](https://www.linkedin.com/in/b-ranjan-kumar)
- 🐙 [GitHub](https://github.com/bituranjankumar)

*Star ⭐ the repo to follow along!*
