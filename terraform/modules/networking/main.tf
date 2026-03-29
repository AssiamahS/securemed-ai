# HIPAA-compliant VPC — no public subnets for PHI workloads

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "hipaa-clinic-${var.environment}" }
}

# Private subnet — LLM and ELK live here, no internet exposure
resource "aws_subnet" "private" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false

  tags = { Name = "hipaa-private-${var.environment}" }
}

# Public subnet — only for NAT gateway (outbound updates)
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 100)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false

  tags = { Name = "hipaa-public-${var.environment}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "hipaa-igw-${var.environment}" }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "hipaa-nat-eip-${var.environment}" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id
  tags          = { Name = "hipaa-nat-${var.environment}" }
}

# Public route table — IGW for NAT subnet only
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "hipaa-public-rt-${var.environment}" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Private route table — NAT for outbound only (system updates)
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "hipaa-private-rt-${var.environment}" }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# VPC Flow Logs — required for HIPAA audit trail
resource "aws_flow_log" "main" {
  vpc_id               = aws_vpc.main.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn         = aws_iam_role.flow_log.arn
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/hipaa/vpc-flow-logs/${var.environment}"
  retention_in_days = 365 # HIPAA requires 6 years, use S3 archival for long-term
}

resource "aws_iam_role" "flow_log" {
  name = "hipaa-flow-log-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "flow_log" {
  name = "flow-log-publish"
  role = aws_iam_role.flow_log.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
      Effect   = "Allow"
      Resource = "*"
    }]
  })
}

data "aws_availability_zones" "available" {
  state = "available"
}

variable "vpc_cidr" { type = string }
variable "environment" { type = string }

output "vpc_id" { value = aws_vpc.main.id }
output "private_subnet_id" { value = aws_subnet.private.id }
