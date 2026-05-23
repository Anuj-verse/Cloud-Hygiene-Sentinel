# NimbusKart — Network module variables


variable "project" {
  description = "Project name — used in resource names and tags"
  type        = string
}

variable "environment" {
  description = "Deployment environment (staging, production, dev)"
  type        = string

  validation {
    condition     = contains(["staging", "production", "dev"], var.environment)
    error_message = "environment must be one of: staging, production, dev."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "public_subnet_cidrs" {
  description = "List of CIDR blocks for public subnets — one per AZ"
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) >= 2
    error_message = "At least 2 public subnet CIDRs are required (one per AZ)."
  }
}

variable "availability_zones" {
  description = "List of AZs to deploy subnets into — must match length of public_subnet_cidrs"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "At least 2 availability zones are required."
  }
}

variable "ssh_allowed_cidr" {
  description = <<-EOT
    CIDR for port 22 on the web security group.
    Empty string disables SSH ingress (the safe default).
    Spec suggested 0.0.0.0/0 — we rejected that.
  EOT
  type        = string
  default     = ""
}

variable "common_tags" {
  description = "Tags applied to every resource in this module (merged with resource-specific tags)"
  type        = map(string)
  default     = {}
}
