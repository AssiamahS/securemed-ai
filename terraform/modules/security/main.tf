# HIPAA Security — KMS encryption, strict security groups, CloudTrail

# ─── KMS Key for encryption at rest ──────────────────────
resource "aws_kms_key" "hipaa" {
  description             = "HIPAA encryption key for clinic LLM"
  deletion_window_in_days = 30
  enable_key_rotation     = true # HIPAA best practice

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootAccount"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      }
    ]
  })
}

resource "aws_kms_alias" "hipaa" {
  name          = "alias/hipaa-clinic-${var.environment}"
  target_key_id = aws_kms_key.hipaa.key_id
}

# ─── LLM Server Security Group ──────────────────────────
resource "aws_security_group" "llm" {
  name_prefix = "hipaa-llm-"
  description = "LLM server — clinic IPs only"
  vpc_id      = var.vpc_id

  # SSH from allowed CIDRs only
  ingress {
    description = "SSH from clinic"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  # LLM API — internal VPC only
  ingress {
    description = "LLM API from VPC"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Ollama — internal VPC only
  ingress {
    description = "Ollama from VPC"
    from_port   = 11434
    to_port     = 11434
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Outbound — NAT only (for system updates)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "hipaa-llm-sg-${var.environment}" }
}

# ─── ELK Security Group ─────────────────────────────────
resource "aws_security_group" "elk" {
  name_prefix = "hipaa-elk-"
  description = "ELK monitoring — internal access only"
  vpc_id      = var.vpc_id

  # Kibana — clinic IPs only
  ingress {
    description = "Kibana from clinic"
    from_port   = 5601
    to_port     = 5601
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  # Elasticsearch — VPC internal only
  ingress {
    description = "Elasticsearch from VPC"
    from_port   = 9200
    to_port     = 9200
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Logstash beats input — VPC internal only
  ingress {
    description = "Logstash from VPC"
    from_port   = 5044
    to_port     = 5044
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # SSH from allowed CIDRs
  ingress {
    description = "SSH from clinic"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "hipaa-elk-sg-${var.environment}" }
}

# ─── CloudTrail — HIPAA audit requirement ────────────────
resource "aws_cloudtrail" "hipaa" {
  name                       = "hipaa-audit-${var.environment}"
  s3_bucket_name             = aws_s3_bucket.audit_logs.id
  include_global_service_events = true
  is_multi_region_trail      = true
  enable_log_file_validation = true
  kms_key_id                 = aws_kms_key.hipaa.arn
}

resource "aws_s3_bucket" "audit_logs" {
  bucket_prefix = "hipaa-audit-logs-"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.hipaa.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit_logs" {
  bucket                  = aws_s3_bucket.audit_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AWSCloudTrailAclCheck"
        Effect = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action   = "s3:GetBucketAcl"
        Resource = aws_s3_bucket.audit_logs.arn
      },
      {
        Sid    = "AWSCloudTrailWrite"
        Effect = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.audit_logs.arn}/*"
        Condition = { StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" } }
      }
    ]
  })
}

data "aws_caller_identity" "current" {}

variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "allowed_cidrs" { type = list(string) }

output "llm_sg_id" { value = aws_security_group.llm.id }
output "elk_sg_id" { value = aws_security_group.elk.id }
output "kms_key_arn" { value = aws_kms_key.hipaa.arn }
