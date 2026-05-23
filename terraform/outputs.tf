# NimbusKart — Root outputs (vpc_id, subnet_ids, bucket_name required by spec)

output "vpc_id" {
  description = "ID of the NimbusKart VPC"
  value       = module.network.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC"
  value       = module.network.vpc_cidr
}

output "public_subnet_ids" {
  description = "IDs of the public subnets (one per AZ)"
  value       = module.network.public_subnet_ids
}

output "public_subnet_cidrs" {
  description = "CIDR blocks of the public subnets"
  value       = module.network.public_subnet_cidrs
}

output "bucket_name" {
  description = "Name of the application logs S3 bucket"
  value       = aws_s3_bucket.app_logs.id
}

output "bucket_arn" {
  description = "ARN of the application logs S3 bucket"
  value       = aws_s3_bucket.app_logs.arn
}

output "web_security_group_id" {
  description = "ID of the web-tier security group"
  value       = module.network.web_security_group_id
}

output "web_instance_ids" {
  description = "IDs of the two web-tier EC2 instances"
  value       = aws_instance.web[*].id
}

output "web_instance_public_ips" {
  description = "Public IPs of the web-tier EC2 instances (assigned by LocalStack)"
  value       = aws_instance.web[*].public_ip
}

output "orphan_ebs_volume_id" {
  description = "ID of the intentional orphan EBS volume — used to test Cost Janitor detection"
  value       = aws_ebs_volume.orphan.id
}