variable "region" {
  description = "Stockholm: the account's plan allows EC2 and Bedrock there, not in Frankfurt (checked 3 October 2026)"
  type        = string
  default     = "eu-north-1"
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
  description = "t4g.small: 2 vCPU ARM, 2 GB RAM"
  type        = string
  default     = "t4g.small"
}

variable "disk_gb" {
  type    = number
  default = 30
}

variable "model_provider" {
  description = "anthropic (API key from Parameter Store) until Bedrock quota is granted, then bedrock (decision 0015)"
  type        = string
  default     = "anthropic"
  validation {
    condition     = contains(["anthropic", "bedrock"], var.model_provider)
    error_message = "model_provider must be anthropic or bedrock."
  }
}

variable "anthropic_key_parameter" {
  description = "SecureString in Parameter Store holding the Anthropic API key; created by hand, never in Terraform state"
  type        = string
  default     = "/upchirp/anthropic-api-key"
}

variable "bedrock_model" {
  description = "EU inference profile, so requests stay in EU regions"
  type        = string
  default     = "eu.anthropic.claude-opus-5-5"
}
