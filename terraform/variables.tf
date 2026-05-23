# NimbusKart — Root variables




variable "project" {
  description = "Project name used in resource names and required Project tag"
  type        = string
  default     = "nimbuskart"
}

variable "environment" {
  description = "Deployment environment — used in names and required Environment tag"
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production", "dev"], var.environment)
    error_message = "environment must be one of: staging, production, dev."
  }
}

variable "owner" {
  description = "Team or individual responsible — used in required Owner tag"
  type        = string
  default     = "platform-team"
}



variable "aws_region" {
  description = "AWS region to deploy into (also used by LocalStack)"
  type        = string
  default     = "us-east-1"
}



variable "vpc_cidr" {
  description = "CIDR block for the VPC — must be /16 per NimbusKart network plan"
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets — one per AZ, must be within vpc_cidr"
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24"]
}

variable "availability_zones" {
  description = "Availability zones to deploy subnets into — length must match public_subnet_cidrs"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "ssh_allowed_cidr" {
  description = <<-EOT
    CIDR allowed inbound on port 22. Empty string disables SSH ingress.
    Pass your operator IP (e.g. "203.0.113.42/32") to enable SSH.
    The spec suggested 0.0.0.0/0 as default — we reject that.
  EOT
  type        = string
  default     = ""
}



variable "instance_type" {
  description = "EC2 instance type for web tier instances"
  type        = string
  default     = "t3.micro"

  validation {
    condition     = can(regex("^t[23]\\.(micro|small|medium)$", var.instance_type))
    error_message = "instance_type must be a t2 or t3 burstable type for staging (micro/small/medium)."
  }
}