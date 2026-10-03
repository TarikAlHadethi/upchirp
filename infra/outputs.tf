output "demo_url" {
  value = "http://${aws_instance.demo.public_dns}"
}

output "instance_id" {
  value = aws_instance.demo.id
}

output "bucket" {
  value = aws_s3_bucket.main.bucket
}
