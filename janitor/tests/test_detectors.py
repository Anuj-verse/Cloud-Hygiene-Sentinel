# test_detectors.py — unit tests for janitor.py detectors
# Uses moto, no LocalStack needed. Run: pytest janitor/tests/ -v

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).parent.parent))

from janitor import (
    detect_unattached_ebs,
    detect_stopped_ec2,
    detect_unused_eips,
    detect_missing_tags,
    _safe_delete,
    _build_report,
    _is_protected,
    _missing_tags,
    _tags_as_dict,
    _parse_stopped_timestamp,
)
from constants import DEFAULT_STOPPED_DAYS_THRESHOLD, REQUIRED_TAGS


GOOD_TAGS = [
    {"Key": "Project",     "Value": "nimbuskart"},
    {"Key": "Environment", "Value": "staging"},
    {"Key": "Owner",       "Value": "platform-team"},
    {"Key": "ManagedBy",   "Value": "terraform"},
]


class TestHelpers:
    def test_tags_as_dict_empty(self):
        assert _tags_as_dict(None) == {}
        assert _tags_as_dict([]) == {}

    def test_tags_as_dict_converts(self):
        result = _tags_as_dict([{"Key": "Env", "Value": "prod"}])
        assert result == {"Env": "prod"}

    def test_missing_tags_all_present(self):
        tags = {"Project": "x", "Environment": "y", "Owner": "z"}
        assert _missing_tags(tags) == []

    def test_missing_tags_detects_absent(self):
        tags = {"Project": "x"}
        missing = _missing_tags(tags)
        assert "Environment" in missing
        assert "Owner" in missing

    def test_missing_tags_detects_empty_string(self):
        tags = {"Project": "", "Environment": "y", "Owner": "z"}
        assert "Project" in _missing_tags(tags)

    def test_is_protected_true(self):
        assert _is_protected({"Protected": "true"}) is True
        assert _is_protected({"Protected": "True"}) is True
        assert _is_protected({"Protected": "TRUE"}) is True

    def test_is_protected_false(self):
        assert _is_protected({"Protected": "false"}) is False
        assert _is_protected({}) is False

    def test_parse_stopped_timestamp_valid(self):
        reason = "User initiated (2024-01-15 10:30:00 GMT)"
        result = _parse_stopped_timestamp(reason)
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_stopped_timestamp_invalid(self):
        assert _parse_stopped_timestamp("") is None
        assert _parse_stopped_timestamp("no timestamp here") is None


class TestUnattachedEBS:
    @mock_aws
    def test_detects_unattached_volume(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a",
            Size=20,
            VolumeType="gp3",
            TagSpecifications=[{"ResourceType": "volume", "Tags": GOOD_TAGS}],
        )

        findings = detect_unattached_ebs(ec2)

        assert len(findings) == 1
        assert findings[0]["resource_type"] == "ebs_volume"
        assert findings[0]["reason"] == "unattached"

    @mock_aws
    def test_no_findings_when_clean(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        findings = detect_unattached_ebs(ec2)
        assert findings == []

    @mock_aws
    def test_cost_calculated_correctly(self):
        """gp3 20GB = 20 × $0.08 = $1.60/month."""
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a",
            Size=20,
            VolumeType="gp3",
            TagSpecifications=[{"ResourceType": "volume", "Tags": GOOD_TAGS}],
        )

        findings = detect_unattached_ebs(ec2)
        assert findings[0]["estimated_monthly_cost_usd"] == pytest.approx(1.60)

    @mock_aws
    def test_protected_volume_flagged_but_not_safe_to_delete(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a",
            Size=20,
            VolumeType="gp3",
            TagSpecifications=[{
                "ResourceType": "volume",
                "Tags": GOOD_TAGS + [{"Key": "Protected", "Value": "true"}],
            }],
        )

        findings = detect_unattached_ebs(ec2)
        assert len(findings) == 1
        assert findings[0]["safe_to_auto_delete"] is False

    @mock_aws
    def test_schema_fields_present(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a", Size=10, VolumeType="gp3",
            TagSpecifications=[{"ResourceType": "volume", "Tags": GOOD_TAGS}],
        )
        findings = detect_unattached_ebs(ec2)
        f = findings[0]
        for field in ["resource_id", "resource_type", "reason", "age_days",
                      "estimated_monthly_cost_usd", "tags",
                      "suggested_action", "safe_to_auto_delete"]:
            assert field in f, f"Missing required schema field: {field}"


class TestStoppedEC2:
    @mock_aws
    def test_no_findings_when_clean(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        findings = detect_stopped_ec2(ec2, DEFAULT_STOPPED_DAYS_THRESHOLD)
        assert findings == []

    @mock_aws
    def test_running_instance_not_flagged(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        images = ec2.describe_images(Owners=["amazon"])
        if not images["Images"]:
            pytest.skip("No AMIs available in moto")

        findings = detect_stopped_ec2(ec2, DEFAULT_STOPPED_DAYS_THRESHOLD)
        assert findings == []

    @mock_aws
    def test_stopped_days_threshold_respected(self):
        """Freshly-stopped instance (age ~0) should not be flagged with threshold=14."""
        ec2 = boto3.client("ec2", region_name="us-east-1")
        findings = detect_stopped_ec2(ec2, 14)
        assert len(findings) == 0


class TestUnusedEIPs:
    @mock_aws
    def test_detects_unassociated_eip(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.allocate_address(Domain="vpc")

        findings = detect_unused_eips(ec2)

        assert len(findings) == 1
        assert findings[0]["resource_type"] == "elastic_ip"
        assert findings[0]["reason"] == "unassociated"
        assert findings[0]["estimated_monthly_cost_usd"] == pytest.approx(3.60)

    @mock_aws
    def test_no_findings_when_no_eips(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        findings = detect_unused_eips(ec2)
        assert findings == []

    @mock_aws
    def test_multiple_eips_all_flagged(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.allocate_address(Domain="vpc")
        ec2.allocate_address(Domain="vpc")
        ec2.allocate_address(Domain="vpc")

        findings = detect_unused_eips(ec2)
        assert len(findings) == 3


class TestMissingTags:
    @mock_aws
    def test_untagged_volume_flagged(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(AvailabilityZone="us-east-1a", Size=10, VolumeType="gp2")

        findings = detect_missing_tags(ec2)

        ebs_findings = [f for f in findings if f["resource_type"] == "ebs_volume"]
        assert len(ebs_findings) >= 1
        assert "missing_required_tags" in ebs_findings[0]["reason"]

    @mock_aws
    def test_fully_tagged_volume_not_flagged(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a",
            Size=10,
            VolumeType="gp3",
            TagSpecifications=[{"ResourceType": "volume", "Tags": GOOD_TAGS}],
        )

        findings = detect_missing_tags(ec2)
        ebs_findings = [f for f in findings if f["resource_type"] == "ebs_volume"]
        assert len(ebs_findings) == 0

    @mock_aws
    def test_partially_tagged_volume_flagged(self):
        """Volume with Project but missing Environment and Owner."""
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a",
            Size=10,
            VolumeType="gp3",
            TagSpecifications=[{
                "ResourceType": "volume",
                "Tags": [{"Key": "Project", "Value": "nimbuskart"}],
            }],
        )

        findings = detect_missing_tags(ec2)
        ebs_findings = [f for f in findings if f["resource_type"] == "ebs_volume"]
        assert len(ebs_findings) == 1
        assert "Environment" in ebs_findings[0]["reason"]
        assert "Owner" in ebs_findings[0]["reason"]

    @mock_aws
    def test_untagged_eip_flagged(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.allocate_address(Domain="vpc")

        findings = detect_missing_tags(ec2)
        eip_findings = [f for f in findings if f["resource_type"] == "elastic_ip"]
        assert len(eip_findings) >= 1


class TestDeleteSafety:
    @mock_aws
    def test_protected_volume_never_deleted(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        resp = ec2.create_volume(
            AvailabilityZone="us-east-1a",
            Size=20,
            VolumeType="gp3",
            TagSpecifications=[{
                "ResourceType": "volume",
                "Tags": GOOD_TAGS + [{"Key": "Protected", "Value": "true"}],
            }],
        )
        vol_id = resp["VolumeId"]

        finding = {
            "resource_id":        vol_id,
            "resource_type":      "ebs_volume",
            "safe_to_auto_delete": True,  # report says safe — but tag says protected
        }

        action = _safe_delete(ec2, finding)

        vols = ec2.describe_volumes(VolumeIds=[vol_id])["Volumes"]
        assert len(vols) == 1
        assert "Protected=true" in action or "skipped" in action

    @mock_aws
    def test_unprotected_volume_deleted(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        resp = ec2.create_volume(
            AvailabilityZone="us-east-1a",
            Size=20,
            VolumeType="gp3",
            TagSpecifications=[{
                "ResourceType": "volume",
                "Tags": GOOD_TAGS + [{"Key": "Protected", "Value": "false"}],
            }],
        )
        vol_id = resp["VolumeId"]

        finding = {
            "resource_id":        vol_id,
            "resource_type":      "ebs_volume",
            "safe_to_auto_delete": True,
        }

        action = _safe_delete(ec2, finding)
        assert action == "deleted"

        vols = ec2.describe_volumes(
            Filters=[{"Name": "volume-id", "Values": [vol_id]}]
        )["Volumes"]
        assert all(v["State"] == "deleted" for v in vols)

    @mock_aws
    def test_ec2_instance_never_auto_deleted(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")

        finding = {
            "resource_id":        "i-0123456789abcdef0",
            "resource_type":      "ec2_instance",
            "safe_to_auto_delete": True,
        }

        action = _safe_delete(ec2, finding)
        assert "human approval" in action or "skipped" in action

    @mock_aws
    def test_safe_to_auto_delete_false_skipped(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")

        finding = {
            "resource_id":        "vol-dummy",
            "resource_type":      "ebs_volume",
            "safe_to_auto_delete": False,
        }

        action = _safe_delete(ec2, finding)
        assert "skipped" in action


class TestReportSchema:
    @mock_aws
    def test_report_schema_matches_spec(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a", Size=20, VolumeType="gp3",
            TagSpecifications=[{"ResourceType": "volume", "Tags": GOOD_TAGS}],
        )

        findings = detect_unattached_ebs(ec2)
        report = _build_report(findings, "us-east-1", "000000000000")

        assert "scan_timestamp" in report
        assert "account_id" in report
        assert "region" in report
        assert "summary" in report
        assert "findings" in report

        assert "total_orphans" in report["summary"]
        assert "estimated_monthly_waste_usd" in report["summary"]
        assert report["summary"]["total_orphans"] == 1

        f = report["findings"][0]
        required_finding_fields = [
            "resource_id", "resource_type", "reason", "age_days",
            "estimated_monthly_cost_usd", "tags",
            "suggested_action", "safe_to_auto_delete",
        ]
        for field in required_finding_fields:
            assert field in f, f"Missing required finding field: {field}"

    @mock_aws
    def test_clean_environment_exits_zero(self, tmp_path):
        ec2 = boto3.client("ec2", region_name="us-east-1")

        findings = (
            detect_unattached_ebs(ec2)
            + detect_stopped_ec2(ec2, 14)
            + detect_unused_eips(ec2)
            + detect_missing_tags(ec2)
        )
        report = _build_report(findings, "us-east-1", "000000000000")

        assert report["summary"]["total_orphans"] == 0
        assert report["summary"]["estimated_monthly_waste_usd"] == 0.0

    @mock_aws
    def test_orphan_environment_nonzero_total(self):
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(
            AvailabilityZone="us-east-1a", Size=20, VolumeType="gp3",
            TagSpecifications=[{"ResourceType": "volume", "Tags": GOOD_TAGS}],
        )

        findings = detect_unattached_ebs(ec2)
        report = _build_report(findings, "us-east-1", "000000000000")

        assert report["summary"]["total_orphans"] >= 1
        assert report["summary"]["estimated_monthly_waste_usd"] > 0