# Submission — DevOps Engineer Assignment

**Candidate name:** Anuj Gope
**Email:** anujfw1234@gmail.com
**Date submitted:** 24/05/2026
**Hours spent (approximate):** 9

## Deliverables checklist

- [x] Part A: Terraform code under /terraform applies cleanly on LocalStack
- [x] Part A: `terraform validate` and `terraform fmt -check` both pass
- [x] Part B: Janitor script runs in --dry-run mode and produces report.json
- [x] Part B: GitHub Actions workflow runs green on a fresh PR
- [x] Part B: --delete mode respects Protected=true tag
- [x] Part C: DESIGN.md is present and within 2 pages

## Walkthrough video

Link (Loom / YouTube unlisted / Google Drive): [YOUR VIDEO LINK]
Length: max 5 minutes

## Sample report

Path to a sample report.json produced by your script: `samples/report.example.json`

## Known limitations

- Multi-account scanning not implemented — single AWS account only
- EBS snapshot age detection not built (would be next sprint)
- GCP provider module boundary is designed but not implemented
- LocalStack uses local Terraform state, not remote S3+DynamoDB backend
- Walkthrough video recorded against LocalStack; no real AWS account used

## AI usage disclosure

Used Claude (Anthropic) for Terraform module scaffolding, GitHub Actions YAML structure, and Moto test boilerplate. One specific error caught: Claude generated a LocalStack health check grep for `"running"` when LocalStack actually returns `"available"` — would have caused the workflow to hang indefinitely. Fixed by manually reading the LocalStack health endpoint. The delete-mode safety re-check logic (re-fetching live tags before deletion to guard against race conditions) was written without AI assistance, reasoning through the edge case step by step.