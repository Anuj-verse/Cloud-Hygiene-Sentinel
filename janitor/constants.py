# NimbusKart Cost Janitor — Pricing constants
#
# US East (us-east-1) on-demand rates.
# Hard-coded so the report works without a live Pricing API call.
# Update when AWS changes prices.

# EBS (per GB-month) — https://aws.amazon.com/ebs/pricing/
EBS_GP2_COST_PER_GB_MONTH: float = 0.10
EBS_GP3_COST_PER_GB_MONTH: float = 0.08
EBS_IO1_COST_PER_GB_MONTH: float = 0.125
EBS_IO2_COST_PER_GB_MONTH: float = 0.125
EBS_ST1_COST_PER_GB_MONTH: float = 0.045
EBS_SC1_COST_PER_GB_MONTH: float = 0.015
EBS_STANDARD_COST_PER_GB_MONTH: float = 0.05
EBS_DEFAULT_COST_PER_GB_MONTH: float = 0.08  # fallback — assume gp3

# Elastic IP — https://aws.amazon.com/vpc/pricing/
# $0.005/hr per idle EIP
EIP_IDLE_COST_PER_HOUR: float = 0.005
EIP_IDLE_COST_PER_MONTH: float = round(EIP_IDLE_COST_PER_HOUR * 24 * 30, 2)  # $3.60

# EC2 on-demand (Linux, us-east-1) — https://aws.amazon.com/ec2/pricing/on-demand/
EC2_HOURLY_RATES: dict[str, float] = {
    "t2.micro":    0.0116,
    "t2.small":    0.023,
    "t2.medium":   0.0464,
    "t3.micro":    0.0104,
    "t3.small":    0.0208,
    "t3.medium":   0.0416,
    "t3.large":    0.0832,
    "t3.xlarge":   0.1664,
    "t3.2xlarge":  0.3328,
    "m5.large":    0.096,
    "m5.xlarge":   0.192,
    "m5.2xlarge":  0.384,
    "c5.large":    0.085,
    "c5.xlarge":   0.17,
    "r5.large":    0.126,
    "r5.xlarge":   0.252,
}
EC2_FALLBACK_HOURLY_RATE: float = 0.0416  # t3.medium as safe middle estimate

# Required tags — Janitor flags anything missing these
REQUIRED_TAGS: list[str] = ["Project", "Environment", "Owner"]

# Thresholds
DEFAULT_STOPPED_DAYS_THRESHOLD: int = 14
HOURS_PER_MONTH: float = 24 * 30  # 720 hours

# LocalStack defaults
LOCALSTACK_ACCOUNT_ID: str = "000000000000"
LOCALSTACK_ENDPOINT:   str = "http://localhost:4566"