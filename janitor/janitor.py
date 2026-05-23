#!/usr/bin/env python3
"""
NimbusKart Cost Janitor — scans for orphaned AWS resources and generates a report.

Usage:
    python janitor.py                        # dry-run (default)
    python janitor.py --delete               # delete safe orphans
    python janitor.py --region us-west-2     # override region
    python janitor.py --endpoint-url http://localhost:4566   # LocalStack
    python janitor.py --stopped-days 7       # custom threshold

Exit codes:  0 = clean,  1 = orphans found,  2 = connection/runtime error
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from constants import (
    DEFAULT_STOPPED_DAYS_THRESHOLD,
    EBS_DEFAULT_COST_PER_GB_MONTH,
    EIP_IDLE_COST_PER_MONTH,
    HOURS_PER_MONTH,
    LOCALSTACK_ACCOUNT_ID,
    LOCALSTACK_ENDPOINT,
    REQUIRED_TAGS,
    EC2_HOURLY_RATES,
    EC2_FALLBACK_HOURLY_RATE,
)

EBS_PRICE_MAP: dict[str, float] = {
    "gp2": 0.10,
    "gp3": 0.08,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# --- Helpers ---

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(dt: datetime) -> int:
    """Full days between *dt* and now."""
    delta = _now_utc() - dt.astimezone(timezone.utc)
    return delta.days


def _tags_as_dict(tag_list: list[dict] | None) -> dict[str, str | None]:
    """AWS tag list → flat dict."""
    if not tag_list:
        return {}
    return {t["Key"]: t["Value"] for t in tag_list}


def _missing_tags(tag_dict: dict[str, str | None]) -> list[str]:
    """Required tag keys that are absent or empty."""
    return [
        key for key in REQUIRED_TAGS
        if not tag_dict.get(key)
    ]


def _is_protected(tag_dict: dict[str, str | None]) -> bool:
    return tag_dict.get("Protected", "").lower() == "true"


def _ebs_monthly_cost(volume_type: str, size_gb: int) -> float:
    price = EBS_PRICE_MAP.get(volume_type, EBS_DEFAULT_COST_PER_GB_MONTH)
    return round(price * size_gb, 2)


def _parse_stopped_timestamp(reason: str) -> datetime | None:
    """
    Parse stop time from StateTransitionReason, e.g.:
    "User initiated (2024-01-15 10:30:00 GMT)"
    """
    match = re.search(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)", reason)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _make_finding(
    resource_id: str,
    resource_type: str,
    reason: str,
    age_days: int,
    estimated_monthly_cost_usd: float,
    tags: dict,
    suggested_action: str,
    safe_to_auto_delete: bool,
) -> dict[str, Any]:
    """Build one finding dict matching the required schema."""
    required_tag_snapshot = {
        key: tags.get(key) for key in REQUIRED_TAGS
    }
    return {
        "resource_id":                resource_id,
        "resource_type":              resource_type,
        "reason":                     reason,
        "age_days":                   age_days,
        "estimated_monthly_cost_usd": estimated_monthly_cost_usd,
        "tags":                       required_tag_snapshot,
        "suggested_action":           suggested_action,
        "safe_to_auto_delete":        safe_to_auto_delete,
        "all_tags":                   tags,
        "protected":                  _is_protected(tags),
    }


# --- Detector 1: Unattached EBS volumes ---

def detect_unattached_ebs(ec2_client) -> list[dict]:
    """EBS volumes in 'available' state (not attached to anything)."""
    log.info("Scanning for unattached EBS volumes...")
    findings: list[dict] = []

    paginator = ec2_client.get_paginator("describe_volumes")
    for page in paginator.paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    ):
        for vol in page["Volumes"]:
            vol_id   = vol["VolumeId"]
            vol_type = vol["VolumeType"]
            size_gb  = vol["Size"]
            created  = vol["CreateTime"]
            tags     = _tags_as_dict(vol.get("Tags"))

            age       = _age_days(created)
            monthly   = _ebs_monthly_cost(vol_type, size_gb)
            protected = _is_protected(tags)

            log.info(
                "  Found unattached EBS: %s  type=%s  size=%dGB  age=%dd  "
                "cost=$%.2f/mo  protected=%s",
                vol_id, vol_type, size_gb, age, monthly, protected,
            )

            findings.append(_make_finding(
                resource_id=vol_id,
                resource_type="ebs_volume",
                reason="unattached",
                age_days=age,
                estimated_monthly_cost_usd=monthly,
                tags=tags,
                suggested_action="delete",
                safe_to_auto_delete=not protected,
            ))

    log.info("  Unattached EBS volumes: %d found", len(findings))
    return findings


# --- Detector 2: EC2 instances stopped > N days ---

def detect_stopped_ec2(ec2_client, stopped_days_threshold: int) -> list[dict]:
    """
    Stopped instances still incur EBS storage costs for their root volume.
    Stop timestamp is parsed from StateTransitionReason; falls back to
    LaunchTime if the string can't be parsed.
    """
    log.info(
        "Scanning for EC2 instances stopped for >%d days...",
        stopped_days_threshold,
    )
    findings: list[dict] = []

    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
    ):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                inst_id   = inst["InstanceId"]
                inst_type = inst["InstanceType"]
                tags      = _tags_as_dict(inst.get("Tags"))
                reason_str = inst.get("StateTransitionReason", "")

                stopped_at = _parse_stopped_timestamp(reason_str)
                timestamp_source = "StateTransitionReason"
                if stopped_at is None:
                    # Fallback: overestimates age but safe
                    stopped_at = inst["LaunchTime"].astimezone(timezone.utc)
                    timestamp_source = "LaunchTime (fallback)"

                age = _age_days(stopped_at)

                if age < stopped_days_threshold:
                    log.debug(
                        "  Skipping %s — stopped %dd ago (threshold=%d)",
                        inst_id, age, stopped_days_threshold,
                    )
                    continue

                # Estimate: root EBS continues to cost even while stopped
                root_vol_cost = _ebs_monthly_cost("gp3", 20)
                protected     = _is_protected(tags)

                log.info(
                    "  Found stopped EC2: %s  type=%s  stopped=%dd ago  "
                    "est=$%.2f/mo  protected=%s  [%s]",
                    inst_id, inst_type, age, root_vol_cost,
                    protected, timestamp_source,
                )

                findings.append(_make_finding(
                    resource_id=inst_id,
                    resource_type="ec2_instance",
                    reason=f"stopped_for_{age}_days",
                    age_days=age,
                    estimated_monthly_cost_usd=root_vol_cost,
                    tags=tags,
                    suggested_action="terminate_after_snapshot",
                    safe_to_auto_delete=False,  # never auto-terminate EC2
                ))

    log.info("  Stopped EC2 instances (>%dd): %d found", stopped_days_threshold, len(findings))
    return findings


# --- Detector 3: Unused Elastic IPs ---

def detect_unused_eips(ec2_client) -> list[dict]:
    """EIPs allocated but not associated — $3.60/mo each."""
    log.info("Scanning for unused Elastic IPs...")
    findings: list[dict] = []

    response = ec2_client.describe_addresses()

    for addr in response["Addresses"]:
        if addr.get("AssociationId"):
            continue

        alloc_id  = addr.get("AllocationId", "N/A")
        public_ip = addr.get("PublicIp", "N/A")
        tags      = _tags_as_dict(addr.get("Tags"))
        protected = _is_protected(tags)

        log.info(
            "  Found unused EIP: %s (%s)  cost=$%.2f/mo  protected=%s",
            public_ip, alloc_id, EIP_IDLE_COST_PER_MONTH, protected,
        )

        findings.append(_make_finding(
            resource_id=alloc_id,
            resource_type="elastic_ip",
            reason="unassociated",
            age_days=0,
            estimated_monthly_cost_usd=EIP_IDLE_COST_PER_MONTH,
            tags=tags,
            suggested_action="release",
            safe_to_auto_delete=not protected,
        ))

    log.info("  Unused Elastic IPs: %d found", len(findings))
    return findings


# --- Detector 4: Missing required tags ---

def detect_missing_tags(ec2_client) -> list[dict]:
    """
    Resources missing Project, Environment, or Owner tags.
    A resource can appear here AND in another detector — missing tags
    are a separate cost-attribution problem.
    """
    log.info("Scanning for resources missing required tags...")
    findings: list[dict] = []

    # EC2 instances
    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                if inst["State"]["Name"] == "terminated":
                    continue

                inst_id  = inst["InstanceId"]
                tags     = _tags_as_dict(inst.get("Tags"))
                missing  = _missing_tags(tags)

                if not missing:
                    continue

                log.info(
                    "  EC2 missing tags: %s  missing=%s",
                    inst_id, missing,
                )
                findings.append(_make_finding(
                    resource_id=inst_id,
                    resource_type="ec2_instance",
                    reason=f"missing_required_tags: {', '.join(missing)}",
                    age_days=_age_days(inst["LaunchTime"].astimezone(timezone.utc)),
                    estimated_monthly_cost_usd=0.0,
                    tags=tags,
                    suggested_action="add_missing_tags",
                    safe_to_auto_delete=False,
                ))

    # EBS volumes
    paginator = ec2_client.get_paginator("describe_volumes")
    for page in paginator.paginate():
        for vol in page["Volumes"]:
            tags    = _tags_as_dict(vol.get("Tags"))
            missing = _missing_tags(tags)

            if not missing:
                continue

            log.info(
                "  EBS missing tags: %s  missing=%s",
                vol["VolumeId"], missing,
            )
            findings.append(_make_finding(
                resource_id=vol["VolumeId"],
                resource_type="ebs_volume",
                reason=f"missing_required_tags: {', '.join(missing)}",
                age_days=_age_days(vol["CreateTime"].astimezone(timezone.utc)),
                estimated_monthly_cost_usd=0.0,
                tags=tags,
                suggested_action="add_missing_tags",
                safe_to_auto_delete=False,
            ))

    # Elastic IPs
    for addr in ec2_client.describe_addresses()["Addresses"]:
        tags    = _tags_as_dict(addr.get("Tags"))
        missing = _missing_tags(tags)

        if not missing:
            continue

        log.info(
            "  EIP missing tags: %s  missing=%s",
            addr.get("PublicIp"), missing,
        )
        findings.append(_make_finding(
            resource_id=addr.get("AllocationId", addr.get("PublicIp", "unknown")),
            resource_type="elastic_ip",
            reason=f"missing_required_tags: {', '.join(missing)}",
            age_days=0,
            estimated_monthly_cost_usd=0.0,
            tags=tags,
            suggested_action="add_missing_tags",
            safe_to_auto_delete=False,
        ))

    log.info("  Resources missing tags: %d found", len(findings))
    return findings


# --- Delete logic ---

def _safe_delete(ec2_client, finding: dict) -> str:
    """
    Delete a single finding if safe. Re-fetches live tags before acting
    to guard against someone adding Protected=true between scan and delete.
    EC2 instances are never auto-terminated.
    """
    rid   = finding["resource_id"]
    rtype = finding["resource_type"]

    if not finding["safe_to_auto_delete"]:
        log.info("  SKIP %s %s — safe_to_auto_delete=False", rtype, rid)
        return "skipped (not safe to auto-delete)"

    # Re-check tags on the live resource before any destructive action
    try:
        if rtype == "ebs_volume":
            vols = ec2_client.describe_volumes(VolumeIds=[rid])["Volumes"]
            if not vols:
                return "skipped (volume no longer exists)"
            current_tags = _tags_as_dict(vols[0].get("Tags"))

        elif rtype == "elastic_ip":
            addrs = ec2_client.describe_addresses(AllocationIds=[rid])["Addresses"]
            if not addrs:
                return "skipped (EIP no longer exists)"
            current_tags = _tags_as_dict(addrs[0].get("Tags"))

        else:
            log.warning("  SKIP EC2 %s — EC2 termination requires human approval", rid)
            return "skipped (EC2 termination requires human approval)"

    except ClientError as exc:
        log.warning("  SKIP %s %s — could not re-fetch: %s", rtype, rid, exc)
        return f"skipped (re-fetch failed: {exc})"

    if _is_protected(current_tags):
        log.warning(
            "  SKIP %s %s — Protected=true on live resource (tag added after scan)",
            rtype, rid,
        )
        return "skipped (Protected=true on live resource)"

    # Execute
    try:
        if rtype == "ebs_volume":
            ec2_client.delete_volume(VolumeId=rid)
            log.info("  DELETED EBS volume %s", rid)
            return "deleted"

        elif rtype == "elastic_ip":
            ec2_client.release_address(AllocationId=rid)
            log.info("  RELEASED Elastic IP %s", rid)
            return "released"

    except ClientError as exc:
        log.error("  FAILED to delete %s %s: %s", rtype, rid, exc)
        return f"failed ({exc})"

    return "no_action"


# --- Report generation ---

def _build_report(
    findings: list[dict],
    region: str,
    account_id: str,
) -> dict:
    total_waste = round(
        sum(f["estimated_monthly_cost_usd"] for f in findings), 2
    )
    return {
        "scan_timestamp":             _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "account_id":                 account_id,
        "region":                     region,
        "summary": {
            "total_orphans":                  len(findings),
            "estimated_monthly_waste_usd":    total_waste,
        },
        "findings": findings,
    }


def _write_json_report(report: dict, path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, default=str))
    log.info("JSON report written → %s", path)


def _write_markdown_report(report: dict, path: Path) -> None:
    """Markdown summary suitable for a GitHub PR comment."""
    lines: list[str] = []
    s = report["summary"]
    orphan_count = s["total_orphans"]
    waste        = s["estimated_monthly_waste_usd"]

    if orphan_count == 0:
        lines += [
            "## ✅ Cost Janitor — No orphans found",
            "",
            f"_Scan completed at {report['scan_timestamp']} — "
            f"region `{report['region']}`_",
        ]
    else:
        lines += [
            "## ⚠️ Cost Janitor — Orphaned resources detected",
            "",
            f"| | |",
            f"|---|---|",
            f"| **Scan time** | `{report['scan_timestamp']}` |",
            f"| **Region** | `{report['region']}` |",
            f"| **Account** | `{report['account_id']}` |",
            f"| **Orphans found** | **{orphan_count}** |",
            f"| **Est. monthly waste** | **${waste:.2f}** |",
            "",
            "### Findings",
            "",
            "| Resource ID | Type | Reason | Age (days) | Est. Cost/mo | Safe to delete |",
            "|---|---|---|---|---|---|",
        ]
        for f in report["findings"]:
            safe = "✅ Yes" if f["safe_to_auto_delete"] else "🔒 No"
            lines.append(
                f"| `{f['resource_id']}` "
                f"| {f['resource_type']} "
                f"| {f['reason']} "
                f"| {f['age_days']} "
                f"| ${f['estimated_monthly_cost_usd']:.2f} "
                f"| {safe} |"
            )

        lines += [
            "",
            "### Suggested actions",
            "",
        ]
        for f in report["findings"]:
            lines.append(
                f"- **`{f['resource_id']}`** ({f['resource_type']}): "
                f"{f['suggested_action']}"
            )

        lines += [
            "",
            "> _Run `python janitor/janitor.py --delete` to remove resources "
            "marked as safe. Resources tagged `Protected=true` are never deleted._",
        ]

    path.write_text("\n".join(lines) + "\n")
    log.info("Markdown report written → %s", path)


# --- CLI ---

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NimbusKart Cost Janitor — detect and optionally remove orphaned AWS resources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Scan only — do not delete anything (default)",
    )
    mode.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Delete resources where safe_to_auto_delete=True (skips Protected=true)",
    )

    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region to scan (default: us-east-1)",
    )
    parser.add_argument(
        "--endpoint-url",
        default=LOCALSTACK_ENDPOINT,
        help=f"AWS endpoint URL (default: {LOCALSTACK_ENDPOINT} for LocalStack)",
    )
    parser.add_argument(
        "--stopped-days",
        type=int,
        default=DEFAULT_STOPPED_DAYS_THRESHOLD,
        help=f"Flag EC2 instances stopped for more than N days (default: {DEFAULT_STOPPED_DAYS_THRESHOLD})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Directory to write report.json and report.md (default: current dir)",
    )
    parser.add_argument(
        "--account-id",
        default=LOCALSTACK_ACCOUNT_ID,
        help=f"AWS account ID for the report (default: {LOCALSTACK_ACCOUNT_ID} for LocalStack)",
    )

    args = parser.parse_args()

    if args.delete:
        args.dry_run = False

    return args


# --- Main ---

def main() -> int:
    args = parse_args()

    mode_label = "DRY-RUN" if args.dry_run else "DELETE"
    log.info("=" * 60)
    log.info("NimbusKart Cost Janitor starting  [mode=%s]", mode_label)
    log.info("  region       : %s", args.region)
    log.info("  endpoint     : %s", args.endpoint_url)
    log.info("  stopped-days : %d", args.stopped_days)
    log.info("  output-dir   : %s", args.output_dir)
    log.info("=" * 60)

    try:
        ec2 = boto3.client(
            "ec2",
            region_name=args.region,
            endpoint_url=args.endpoint_url,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        ec2.describe_availability_zones()
    except (BotoCoreError, ClientError, Exception) as exc:
        log.error("Cannot connect to AWS/LocalStack: %s", exc)
        log.error("Is LocalStack running? Try: docker run --rm -d -p 4566:4566 localstack/localstack")
        return 2

    # Run all four detectors
    all_findings: list[dict] = []

    try:
        all_findings += detect_unattached_ebs(ec2)
        all_findings += detect_stopped_ec2(ec2, args.stopped_days)
        all_findings += detect_unused_eips(ec2)
        all_findings += detect_missing_tags(ec2)
    except (BotoCoreError, ClientError) as exc:
        log.error("Detector failed with AWS error: %s", exc)
        return 2

    # Build and write reports
    report = _build_report(all_findings, args.region, args.account_id)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_report(report, args.output_dir / "report.json")
    _write_markdown_report(report, args.output_dir / "report.md")

    total    = report["summary"]["total_orphans"]
    waste    = report["summary"]["estimated_monthly_waste_usd"]
    log.info("=" * 60)
    log.info("Scan complete — %d orphan(s) found  est. waste $%.2f/mo", total, waste)

    if args.delete and all_findings:
        log.info("DELETE mode — processing %d finding(s)...", len(all_findings))
        for finding in all_findings:
            action = _safe_delete(ec2, finding)
            finding["action_taken"] = action

        # Rewrite with action_taken populated
        _write_json_report(report, args.output_dir / "report.json")
        _write_markdown_report(report, args.output_dir / "report.md")

    log.info("=" * 60)

    # Non-zero exit when orphans found — CI blocks the PR
    if all_findings:
        log.warning("Exiting with code 1 — orphans found. Review report.json.")
        return 1

    log.info("Exiting with code 0 — environment is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())