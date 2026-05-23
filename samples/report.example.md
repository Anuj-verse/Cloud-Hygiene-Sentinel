# 🗑️ Cost Janitor Report

**Scan time:** 2026-05-23T10:00:00Z
**Account:** 000000000000
**Region:** us-east-1

## Summary

| Metric | Value |
|---|---|
| Total orphans found | 3 |
| Estimated monthly waste | **$5.20** |

## Findings

### 1. Unattached EBS Volume — `vol-0a1b2c3d4e5f67890`

| Field | Value |
|---|---|
| Type | `ebs_volume` |
| Reason | `unattached` |
| Age | 7 days |
| Est. monthly cost | $0.80 |
| Suggested action | delete |
| Safe to auto-delete | ❌ No |

**Tags:** Project=NimbusKart, Environment=staging, Owner=platform-team, ManagedBy=terraform

---

### 2. Stopped EC2 Instance — `i-0deadbeef1234567`

| Field | Value |
|---|---|
| Type | `ec2_instance` |
| Reason | `stopped_over_threshold` (21 days, threshold 14) |
| Age | 21 days |
| Est. monthly cost | $0.00 (stopped instances accrue EBS cost only) |
| Suggested action | review |
| Safe to auto-delete | ❌ No — EC2 termination always requires human review |

**Tags:** Project=NimbusKart, Environment=staging, Owner=platform-team, Tier=web

---

### 3. Idle Elastic IP — `eipalloc-0abc123def456789`

| Field | Value |
|---|---|
| Type | `elastic_ip` |
| Reason | `not_associated` + `missing_required_tags` |
| Age | 14 days |
| Est. monthly cost | $3.60 |
| Suggested action | release (after adding tags) |
| Safe to auto-delete | ✅ Yes (not_associated finding only) |

**Tags:** ⚠️ All required tags missing (Project, Environment, Owner)

---

## Action required

To dismiss this report, either:
1. Delete or tag the resources listed above, or
2. Tag any resource with `Protected=true` to exclude it from future scans

*Cost estimates use static prices from [constants.py](../janitor/constants.py). Sources cited inline.*
