# Walkthrough — Cloud Hygiene Sentinel

## 📺 Video Demonstration

[Replace this with your Loom / YouTube Unlisted / Google Drive link]

---

## Overview

The Cloud Hygiene Sentinel is a FinOps automation system designed to detect and report orphaned cloud resources before they cause billing spikes.

In the video walkthrough above, I demonstrate:
1. Provisioning the staging infrastructure using Terraform (via LocalStack).
2. Running the Cost Janitor to detect orphaned resources (like an unattached EBS volume).
3. Simulating waste generation by creating an unassociated Elastic IP and demonstrating how the Janitor catches it.
4. Using the `--delete` safety mechanism which verifies live tags (e.g., `Protected=true`) before terminating resources.
5. Reviewing the GitHub Actions CI pipeline that runs these checks automatically on pull requests.

---

## Transcript

*(Optional: Paste the auto-generated transcript from Loom here)*