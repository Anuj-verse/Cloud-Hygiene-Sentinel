# NimbusKart Cost Janitor — DevOps Assignment

## Overview

This repository contains a production-style solution to the Code & Conscience DevOps assignment. It provisions NimbusKart's staging AWS infrastructure using Terraform targeting LocalStack (no real cloud account needed), runs a Python "Cost Janitor" that detects orphaned resources and generates a cost report, and wires both together in a GitHub Actions workflow that runs on every PR — blocking merges when waste is found. The stack intentionally includes one orphaned EBS volume so the Janitor always has something to find.

---

## How to run locally

**Prerequisites:** Docker, Python 3.10+, Git.

```bash
# 1. Clone
git clone https://github.com/Anuj-verse/Cloud-Hygiene-Sentinel.git
cd Cloud-Hygiene-Sentinel

# 2. Start LocalStack
docker run --rm -d -p 4566:4566 --name localstack \
  -e SERVICES=ec2,s3,iam,sts \
  localstack/localstack

# Wait ~15 seconds, then verify:
curl -sf http://localhost:4566/_localstack/health | python3 -m json.tool

# 3. Install tflocal and apply Terraform
pip install terraform-local==0.18.0
cd terraform/
tflocal init
tflocal apply -auto-approve
cd ..

# 4. Install Janitor dependencies
pip install -r janitor/requirements.txt

# 5. Run unit tests (no LocalStack needed — uses Moto)
cd janitor && pytest tests/ -v && cd ..

# 6. Run the Janitor in dry-run mode against LocalStack
python janitor/janitor.py \
  --endpoint-url http://localhost:4566 \
  --dry-run \
  --output-dir samples/

# View report
cat samples/report.json
cat samples/report.md

# 7. Clean up
docker stop localstack
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         GitHub Actions                              │
│                                                                     │
│  PR opened/updated                                                  │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────┐    tflocal apply    ┌─────────────────────────┐  │
│  │  Terraform   │ ─────────────────▶  │   LocalStack (Docker)   │  │
│  │  (IaC)       │                     │   VPC / EC2 / S3 / EBS  │  │
│  └──────────────┘                     └────────────┬────────────┘  │
│                                                    │ boto3 calls   │
│                                                    ▼               │
│                                       ┌────────────────────────┐   │
│                                       │   Cost Janitor (Python) │   │
│                                       │   ┌──────────────────┐  │   │
│                                       │   │ EBS detector     │  │   │
│                                       │   │ EC2 detector     │  │   │
│                                       │   │ EIP detector     │  │   │
│                                       │   │ Tag detector     │  │   │
│                                       │   └────────┬─────────┘  │   │
│                                       └────────────┼────────────┘   │
│                                                    │               │
│                          ┌─────────────────────────┤               │
│                          ▼                         ▼               │
│                   ┌─────────────┐         ┌──────────────┐        │
│                   │ report.json │         │  report.md   │        │
│                   │ (artifact)  │         │ (PR comment) │        │
│                   └─────────────┘         └──────────────┘        │
│                                                                     │
│  exit 1 if orphans found → PR blocked                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Decisions & deviations

- **SSH 0.0.0.0/0 (port 22) — changed to dynamic block.** The spec says default to `0.0.0.0/0` but tells you to flag it. We use a `dynamic "ingress"` block that omits the SSH rule entirely when `ssh_allowed_cidr = ""` (our default). SSH ingress does not exist in the security group unless explicitly enabled with a specific CIDR like `"203.0.113.42/32"`. Opening SSH to the whole internet is how servers get compromised within hours.
- **EC2 instances distributed one per AZ.** The spec says "two t3.micro EC2 instances" but doesn't specify AZ placement. Placing both in the same AZ means an AZ failure takes down the web tier entirely. We distribute one per AZ.
- **Root EBS volumes encrypted.** Not required by the spec. Added because unencrypted root volumes are a common compliance finding and cost nothing extra.
- **S3 bucket: public access blocked + SSE-S3 + incomplete multipart upload lifecycle rule.** The spec only requires versioning and a 30-day non-current expiry rule. The extras are free hygiene that prevent accidental data exposure and silent cost accumulation from abandoned multipart uploads.
- **Orphan EBS tagged `Protected=false` explicitly.** Makes the Janitor's delete-mode logic unambiguous — the tag is present and false, not absent.
- **`ManagedBy = "terraform"` on every resource.** The spec requires this tag. We enforce it via a `locals` block so it can never be accidentally omitted on a new resource.
- **LocalStack state stored locally, not in S3+DynamoDB.** LocalStack's DynamoDB free tier has inconsistent state locking support. Local state is correct for this assignment. A production deployment would use S3 backend + DynamoDB lock table.

---

## Trade-offs

With one more week I would add:

1. **Multi-account scanning** via AWS Organizations + STS `AssumeRole`. The current Janitor is single-account only.
2. **EBS snapshot age detector** — old snapshots are NimbusKart's third-largest waste category, not built due to time budget.
3. **Drift detection** — compare Terraform state against actual LocalStack state and flag resources that exist in AWS but not in state (manually created, forgotten).
4. **Slack webhook integration** in the GitHub Actions workflow, so the PR comment also pings `#finops-alerts`.
5. **`terraform plan` output posted as a second PR comment** alongside the cost report, so reviewers see infra changes and cost impact in one view.

---

## AI usage disclosure

- **Tools used:** Claude (Anthropic) for Terraform module scaffolding, GitHub Actions YAML structure, and Moto test boilerplate.
- **One thing AI got wrong:** Claude initially generated the GitHub Actions service container health check using `grep '"ec2": "running"'` — but LocalStack returns `"available"` not `"running"` for healthy services. The workflow would hang forever waiting for a string that never appears. Caught by reading the LocalStack health endpoint response manually and cross-checking the LocalStack docs.
- **One section written without AI:** The `--delete` safety re-check logic in `janitor.py` — specifically, the part that re-fetches live tags from AWS immediately before deleting, rather than trusting the scan-time tag values. I wrote this manually because the race condition (resource tagged after scan but before delete) is subtle and I wanted to reason through it step by step rather than accept generated code I hadn't thought through.
