# Step 6: the public demo. One small ARM server in Stockholm running the platform in replay
# mode, a private bucket for releases, least-privilege roles, and a monthly budget alarm.
# No SSH: the server is reached through SSM. The model is Bedrock with the server's role,
# or, until Bedrock quota is granted, the Anthropic API with a key the role reads from
# Parameter Store at deploy time (decision 0015). No key is in the repo or Terraform state.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
  default_tags {
    tags = { Project = "upchirp", ManagedBy = "terraform" }
  }
}

data "aws_caller_identity" "me" {}

locals {
  account = data.aws_caller_identity.me.account_id
  bucket  = "upchirp-${local.account}-${var.region}"
}

# ---------- storage: releases (and later recordings) ----------

resource "aws_s3_bucket" "main" {
  bucket = local.bucket
}

resource "aws_s3_bucket_public_access_block" "main" {
  bucket                  = aws_s3_bucket.main.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "main" {
  bucket = aws_s3_bucket.main.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  bucket = aws_s3_bucket.main.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Refuse any request that is not over TLS
resource "aws_s3_bucket_policy" "tls_only" {
  bucket     = aws_s3_bucket.main.id
  depends_on = [aws_s3_bucket_public_access_block.main]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.main.arn, "${aws_s3_bucket.main.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---------- budget alarm ----------

resource "aws_budgets_budget" "monthly" {
  name         = "upchirp-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---------- server role: read releases, call one model, be managed by SSM ----------

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "demo" {
  name               = "upchirp-demo-server"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

data "aws_iam_policy_document" "demo" {
  statement {
    sid       = "ReadReleases"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.main.arn}/releases/*"]
  }
  dynamic "statement" {
    for_each = var.model_provider == "bedrock" ? [1] : []
    content {
      sid     = "InvokeOneModel"
      actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      resources = [
        "arn:aws:bedrock:${var.region}:${local.account}:inference-profile/${var.bedrock_model}",
        # an EU inference profile routes to the model in any EU region
        "arn:aws:bedrock:eu-*::foundation-model/${replace(var.bedrock_model, "eu.", "")}",
      ]
    }
  }
  dynamic "statement" {
    for_each = var.model_provider == "anthropic" ? [1] : []
    content {
      sid       = "ReadOneKey"
      actions   = ["ssm:GetParameter"]
      resources = ["arn:aws:ssm:${var.region}:${local.account}:parameter${var.anthropic_key_parameter}"]
    }
  }
}

resource "aws_iam_role_policy" "demo" {
  name   = "upchirp-demo"
  role   = aws_iam_role.demo.id
  policy = data.aws_iam_policy_document.demo.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.demo.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "demo" {
  name = "upchirp-demo-server"
  role = aws_iam_role.demo.name
}

# ---------- network: default VPC, only HTTP in ----------

data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "demo" {
  name        = "upchirp-demo"
  description = "Public demo: HTTP in, anything out"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description      = "HTTP"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}

# ---------- the server ----------

data "aws_ssm_parameter" "al2023_arm" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "demo" {
  ami                    = data.aws_ssm_parameter.al2023_arm.value
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.demo.name
  vpc_security_group_ids = [aws_security_group.demo.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = var.disk_gb
    encrypted   = true
  }

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # containers can reach the role credentials
  }

  user_data = <<-EOT
    #!/bin/bash
    for i in $(seq 1 60); do
      aws s3 cp --region ${var.region} s3://${local.bucket}/releases/server-setup.sh /root/server-setup.sh && break
      sleep 10
    done
    bash /root/server-setup.sh ${local.bucket} ${var.region} ${var.model_provider} ${var.anthropic_key_parameter} > /var/log/upchirp-setup.log 2>&1
  EOT

  user_data_replace_on_change = false
  tags                        = { Name = "upchirp-demo" }

  lifecycle {
    ignore_changes = [ami] # a newer AMI should not replace a running demo
  }
}
