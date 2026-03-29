variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to access the clinic LLM (your office IPs)"
  type        = list(string)
  # IMPORTANT: Replace with your clinic's actual IP ranges
  # Never use 0.0.0.0/0 for HIPAA workloads
}

variable "llm_instance_type" {
  description = "EC2 instance type for the LLM server"
  type        = string
  default     = "t3.xlarge" # 16GB RAM — runs Qwen 13B
}

variable "elk_instance_type" {
  description = "EC2 instance type for ELK stack"
  type        = string
  default     = "t3.large" # 8GB RAM for Elasticsearch
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
}
