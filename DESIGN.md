# DESIGN.md — Cost Janitor: Hardening, Scale & Multi-Cloud

> Max 2 pages. All answers are specific to NimbusKart's context.

---

## 1. Multi-Cloud Reality — Adding GCP (and Later Azure)

The current janitor mixes cloud-SDK calls with detection logic inside a single file. That breaks the moment you add a second provider. The fix is a three-layer architecture:

```
janitor/
├── core/
│   ├── finding.py        # Finding dataclass — the only schema both layers share
│   ├── reporter.py       # Builds report.json + report.md from a list of Finding objects
│   └── runner.py         # Orchestrates: collect findings → deduplicate → report → exit code
├── providers/
│   ├── base.py           # Abstract BaseProvider with detect() → list[Finding]
│   ├── aws/
│   │   ├── ebs.py        # EBS detector (boto3)
│   │   ├── ec2.py        # Stopped EC2 detector
│   │   └── eip.py        # Elastic IP detector
│   ├── gcp/
│   │   ├── disks.py      # Unattached PD detector (google-cloud-compute)
│   │   └── instances.py  # Stopped GCE detector
│   └── azure/            # (future)
└── janitor.py            # CLI entry point — instantiates providers, calls runner
```

**Key rule:** `core/` imports nothing from `providers/`. Providers import `Finding` from `core/finding.py` and nothing else. Adding GCP means writing two new files under `providers/gcp/` and registering them in `janitor.py`. The reporter, schema, exit-code logic, and tests for core behaviour never change.

---

## 2. Permissions — Minimal IAM Policy

**Dry-run mode** (read-only — list and describe, never mutate):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostJanitorReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "ec2:DescribeSnapshots",
        "ec2:DescribeTags",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

**Delete mode** adds exactly these actions and nothing broader:

```
"ec2:DeleteVolume",
"ec2:ReleaseAddress",
"ec2:DeleteSnapshot"
```

`ec2:TerminateInstances` is **never** granted to the Janitor role — EC2 deletion requires a separate human-approved pipeline. This is a hard constraint, not a configuration option.

---

## 3. Safety Net — Two Specific Failure Modes

**Failure mode 1 — Stopped EC2 is a scheduled batch job**
NimbusKart runs a nightly ETL that starts, processes, and stops a `t3.large` instance. The Janitor sees it stopped for 16 days (because it ran on a Tuesday and today is Thursday two weeks later) and marks it for deletion. Auto-deleting it wipes the instance profile, attached EBS, and cron configuration.

*Guardrail:* Before flagging any stopped EC2, check for a tag `ScheduledStop=true` or a CloudWatch Events rule targeting that instance ID. If either exists, downgrade the finding to `suggested_action: review` and set `safe_to_auto_delete: false`. Additionally, `--delete` mode never terminates EC2 — it only stops, and only after a second confirmation flag `--confirm-ec2-stop`.

**Failure mode 2 — Unattached EBS is a volume being migrated**
A volume gets detached from instance A at 14:00 and will be re-attached to instance B at 14:30 as part of a blue/green deployment. The Janitor runs at 14:15, sees the volume as `available`, calculates age = 0 days, cost = $0.80, and in `--delete` mode removes it. The deployment fails at 14:30 with a missing-volume error.

*Guardrail:* Only delete EBS volumes that have been in `available` state for more than a minimum age threshold (default 48 hours, configurable via `--min-ebs-age-hours`). The current `available` state start time is available via `ec2:DescribeVolumeStatus` — use it, not the volume creation time.

---

## 4. Observability — 5 FinOps Metrics

| Metric | Source | Where to publish | Alert threshold |
|---|---|---|---|
| `janitor.orphans_found` (count) | `summary.total_orphans` in report.json | CloudWatch custom namespace `NimbusKart/CostJanitor` | > 10 for 2 consecutive scans |
| `janitor.estimated_waste_usd` (gauge) | `summary.estimated_monthly_waste_usd` | CloudWatch + Grafana dashboard | > $200/month |
| `janitor.scan_duration_seconds` | Timer around `runner.py` | CloudWatch | > 120s (indicates API throttling or hung detector) |
| `janitor.resources_deleted` (count) | Incremented in `--delete` mode only | CloudWatch + SNS → Slack `#finops-alerts` | Any deletion in production account triggers immediate Slack notification |
| `janitor.missing_tag_violations` (count) | Findings with `reason=missing_required_tags` | CloudWatch | > 0 for 3 consecutive days (signals a Terraform module not applying tags) |

All five are written to CloudWatch via `boto3.client('cloudwatch').put_metric_data()` at the end of each scan run. The Grafana dashboard consumes CloudWatch as a data source. The $200 threshold maps to roughly 10% of NimbusKart's current $2,100 bill.

---

## 5. What I Did Not Build

Consciously left out to hit the 6–10 hour budget:

- **Multi-account scanning** — the Janitor assumes a single AWS account. A real FinOps tool uses AWS Organizations + STS `AssumeRole` to iterate over all member accounts. The `runner.py` abstraction above is designed to accept a list of account/role pairs, but the cross-account role assumption is not implemented.
- **Snapshot age detection** — old EBS snapshots are NimbusKart's third-largest cost driver after unattached volumes and idle EIPs, but the schema and detector logic would add ~2 hours. Flagged for next sprint.
- **GCP provider** — the module boundary is built; the actual `google-cloud-compute` calls are not. Adding GCP is ~4 hours of new provider code with zero changes to core.
- **Slack/PagerDuty integration** — the PR comment covers the CI use case. A production deployment would fan out via SNS → Lambda → Slack webhook. Not built because it requires secrets management that goes beyond the LocalStack scope.
- **Terraform state locking on LocalStack** — LocalStack's DynamoDB support for state locking is inconsistent in the free tier. The LocalStack setup uses local state. A real deployment uses S3 + DynamoDB for remote state.