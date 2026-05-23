# Walkthrough — NimbusKart Cost Janitor

## Video link

[Replace this with your Loom/YouTube unlisted/Google Drive link]

---

## Script outline (5-minute walkthrough)

Use this as your talking guide when recording. You don't need to follow it word for word.

### Minute 0:00 – 1:00 | Start LocalStack and apply Terraform

```bash
# Show terminal — start LocalStack
docker run --rm -d -p 4566:4566 --name localstack \
  -e SERVICES=ec2,s3,iam,sts localstack/localstack

# Confirm healthy
curl -sf http://localhost:4566/_localstack/health | python3 -m json.tool

# Apply Terraform
cd terraform/
tflocal init
tflocal apply -auto-approve
```

**Say:** "I'm pointing Terraform at LocalStack instead of real AWS using the `tflocal` wrapper. The provider block has endpoint overrides for every AWS service — LocalStack intercepts all API calls locally. You can see it created the VPC, two subnets across two AZs, two EC2 instances for the web tier, an S3 bucket, and one unattached EBS volume — that last one is our intentional orphan."

---

### Minute 1:00 – 2:30 | Run the Janitor and walk through a finding

```bash
cd ..
python janitor/janitor.py \
  --endpoint-url http://localhost:4566 \
  --dry-run \
  --output-dir samples/

cat samples/report.json | python3 -m json.tool | head -50
```

**Say:** "The Janitor exits with code 1 — that's intentional. It means CI will fail and block the PR when waste is found. Let me look at the first finding..."

Point to the EBS volume finding in the JSON output:
- `resource_id`: the volume ID Terraform created
- `reason`: `"unattached"`
- `estimated_monthly_cost_usd`: 0.80 (10GB × $0.08/GB-month)
- `safe_to_auto_delete`: false — I set this to false for EBS by default because a volume could be mid-migration between instances

**Say:** "Notice `safe_to_auto_delete` is false even though this is clearly orphaned. In --delete mode, the Janitor will re-fetch the live tags right before deletion — not trust the scan-time snapshot — to guard against a race condition where someone tags a resource Protected=true between the scan and the delete."

---

### Minute 2:30 – 3:30 | Design decision you're proud of

Open `terraform/modules/network/main.tf` and scroll to the security group dynamic block.

**Say:** "The spec says to default SSH to 0.0.0.0/0 but told us to flag it. I went further than just changing the default — I used a dynamic ingress block that completely omits the SSH rule when `ssh_allowed_cidr` is empty. That means the rule literally doesn't exist in the security group. It's not `0.0.0.0/0` with a comment saying 'fix this later' — it's absent. That's the right default for anything internet-facing."

---

### Minute 3:30 – 4:30 | One thing you would change

**Say:** "The thing I'd change first is the stopped EC2 detection. Right now it parses the stop timestamp from `StateTransitionReason` — a human-readable string that looks like `'User initiated (2024-01-15 10:00:00 GMT)'`. That's fragile. If AWS ever changes the format, the regex silently falls back to using `LaunchTime` instead, which is documented in the code but still not ideal. The correct fix is to subscribe to EC2 state-change CloudTrail events and record the stop time in a DynamoDB table — then the Janitor queries that table instead of parsing a string. That's a 3-hour fix I'd prioritise in the next sprint."

---

### Minute 4:30 – 5:00 | Show the GitHub Actions workflow

Navigate to the Actions tab in GitHub (or show the YAML file).

**Say:** "The workflow spins up LocalStack as a service container, applies Terraform, runs the unit tests with Moto — those don't need LocalStack at all, just Python — and then runs the Janitor against the live LocalStack. If orphans are found, it posts the Markdown report as a PR comment and fails the job. The evaluator can fork this repo, open a PR, and watch all of this run without touching a single credential."

---

## Transcript

[Optional: paste auto-generated transcript from Loom here after recording]