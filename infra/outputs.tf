output "demo_url" {
  value = "http://${aws_eip.demo.public_dns}"
}

output "instance_id" {
  value = aws_instance.demo.id
}

output "bucket" {
  value = aws_s3_bucket.main.bucket
}

output "model_provider" {
  value = var.model_provider
}

output "anthropic_key_parameter" {
  value = var.anthropic_key_parameter
}
