output "llm_server_private_ip" {
  description = "Private IP of the LLM server (access via VPN only)"
  value       = module.compute.llm_private_ip
}

output "elk_private_ip" {
  description = "Private IP of ELK monitoring server"
  value       = module.compute.elk_private_ip
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "kms_key_arn" {
  description = "KMS key ARN used for encryption"
  value       = module.security.kms_key_arn
}
