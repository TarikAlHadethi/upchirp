variable "region" {
  description = "Frankfurt: nearest region with Claude on Bedrock (checked 3 October 2026)"
  type        = string
  default     = "eu-central-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile (signed in with `aws login --profile upchirp`)"
  type        = string
  default     = "upchirp"
}

variable "alert_email" {
  description = "Where budget alarms go"
  type        = string
}

variable "monthly_budget_usd" {
  type    = number
  default = 25
}

variable "instance_type" {
  description = "t4g.small: 2 vCPU ARM, 2 GB RAM, $0.0192 per hour in Frankfurt"
  type        = string
  default     = "t4g.small"
}

variable "disk_gb" {
  type    = number
  default = 30
}

variable "bedrock_model" {
  description = "EU inference profile, so requests stay in EU regions"
  type        = string
  default     = "eu.anthropic.claude-opus-5-5"
}
