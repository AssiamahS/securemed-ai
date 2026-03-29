terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "hipaa-terraform-state"
    key            = "clinic/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "hipaa-clinic-llm"
      Environment = var.environment
      ManagedBy   = "terraform"
      Compliance  = "HIPAA"
    }
  }
}

# ─── Networking ───────────────────────────────────────────
module "networking" {
  source      = "./modules/networking"
  environment = var.environment
  vpc_cidr    = var.vpc_cidr
}

# ─── Security ────────────────────────────────────────────
module "security" {
  source         = "./modules/security"
  environment    = var.environment
  vpc_id         = module.networking.vpc_id
  allowed_cidrs  = var.allowed_cidrs
}

# ─── Compute (LLM Server + ELK) ─────────────────────────
module "compute" {
  source              = "./modules/compute"
  environment         = var.environment
  subnet_id           = module.networking.private_subnet_id
  security_group_id   = module.security.llm_sg_id
  elk_security_group_id = module.security.elk_sg_id
  instance_type       = var.llm_instance_type
  elk_instance_type   = var.elk_instance_type
  key_name            = var.key_name
  kms_key_arn         = module.security.kms_key_arn
}
