# NimbusKart — Root Terraform configuration
# Targets LocalStack (http://localhost:4566) via tflocal wrapper

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# LocalStack endpoint override — tflocal sets this automatically.
# When running against real AWS, remove the endpoints block.
provider "aws" {
  region                      = var.aws_region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    ec2 = "http://localhost:4566"
    s3  = "http://localhost:4566"
    iam = "http://localhost:4566"
  }
}

# Common tags applied to every resource — the Janitor flags anything missing these.

locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    Owner       = var.owner
    ManagedBy   = "terraform"
  }
}

# --- Network module ---
module "network" {
  source = "./modules/network"

  project     = var.project
  environment = var.environment

  vpc_cidr            = var.vpc_cidr
  public_subnet_cidrs = var.public_subnet_cidrs
  availability_zones  = var.availability_zones

  # Defaults to "" which disables SSH entirely — see README "Decisions & deviations"
  ssh_allowed_cidr = var.ssh_allowed_cidr

  common_tags = local.common_tags
}

# AMI lookup — LocalStack returns a stub; real AWS resolves latest AL2023
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# EC2 web tier — one instance per AZ for basic HA
resource "aws_instance" "web" {
  count = 2

  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  subnet_id              = module.network.public_subnet_ids[count.index]
  vpc_security_group_ids = [module.network.web_security_group_id]

  # Root volume
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20
    delete_on_termination = true
    encrypted             = true

    tags = merge(local.common_tags, {
      Name = "${var.project}-${var.environment}-web-${count.index + 1}-root"
    })
  }

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-web-${count.index + 1}"
    Tier = "web"
  })
}

# S3 bucket — application logs
resource "aws_s3_bucket" "app_logs" {
  bucket = "${var.project}-${var.environment}-app-logs"

  tags = merge(local.common_tags, {
    Name    = "${var.project}-${var.environment}-app-logs"
    Purpose = "application-logs"
  })
}

# Versioning
resource "aws_s3_bucket_versioning" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Lifecycle: expire non-current versions after 30 days
resource "aws_s3_bucket_lifecycle_configuration" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  depends_on = [aws_s3_bucket_versioning.app_logs]

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    # Abort stale multipart uploads
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE
resource "aws_s3_bucket_server_side_encryption_configuration" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Intentional orphan EBS — unattached on purpose for the Janitor to detect
resource "aws_ebs_volume" "orphan" {
  availability_zone = var.availability_zones[0]
  size              = 20
  type              = "gp3"
  encrypted         = true

  tags = merge(local.common_tags, {
    Name      = "${var.project}-${var.environment}-orphan-ebs"
    Purpose   = "intentional-orphan-for-cost-janitor-testing"
    Protected = "false"
  })
}