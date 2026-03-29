# HIPAA Compute — LLM server + ELK monitoring

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

# ─── LLM Server ─────────────────────────────────────────
resource "aws_instance" "llm" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  key_name               = var.key_name

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
    encrypted   = true
    kms_key_id  = var.kms_key_arn
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only — prevents SSRF
    http_endpoint = "enabled"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # System updates
    apt-get update && apt-get upgrade -y
    apt-get install -y curl jq python3-pip python3-venv auditd

    # Enable auditd for HIPAA compliance
    systemctl enable auditd
    systemctl start auditd

    # Install Ollama
    curl -fsSL https://ollama.com/install.sh | sh

    # Pull Qwen model
    ollama pull qwen2.5:7b

    # Install Filebeat (ships logs to ELK)
    curl -fsSL https://artifacts.elastic.co/GPG-KEY-elasticsearch | gpg --dearmor -o /usr/share/keyrings/elastic.gpg
    echo "deb [signed-by=/usr/share/keyrings/elastic.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main" > /etc/apt/sources.list.d/elastic.list
    apt-get update && apt-get install -y filebeat

    # Configure Filebeat to ship audit + app logs to ELK
    cat > /etc/filebeat/filebeat.yml <<'FBEOF'
    filebeat.inputs:
      - type: log
        paths:
          - /var/log/audit/audit.log
        tags: ["auditd", "hipaa"]
      - type: log
        paths:
          - /opt/hipaa-llm/logs/audit.log
        tags: ["llm-audit", "hipaa"]
      - type: log
        paths:
          - /var/log/syslog
        tags: ["system"]

    output.logstash:
      hosts: ["${var.elk_private_ip:-elk-pending}:5044"]
      ssl.enabled: true

    logging.level: warning
    FBEOF

    systemctl enable filebeat

    # Set up the LLM API
    mkdir -p /opt/hipaa-llm
    cd /opt/hipaa-llm
    python3 -m venv venv
    source venv/bin/activate
    pip install fastapi uvicorn httpx pyyaml python-multipart

    echo "LLM server provisioned at $(date)" >> /var/log/hipaa-setup.log
  EOF

  tags = { Name = "hipaa-llm-${var.environment}" }
}

# ─── ELK Monitoring Server ──────────────────────────────
resource "aws_instance" "elk" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.elk_instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.elk_security_group_id]
  key_name               = var.key_name

  root_block_device {
    volume_size = 100 # ELK needs space for log retention
    volume_type = "gp3"
    encrypted   = true
    kms_key_id  = var.kms_key_arn
  }

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    apt-get update && apt-get upgrade -y
    apt-get install -y curl docker.io docker-compose-v2 auditd

    systemctl enable docker auditd
    systemctl start docker auditd

    # Create ELK docker-compose
    mkdir -p /opt/elk
    # docker-compose.yml is deployed via CI/CD
    echo "ELK server provisioned at $(date)" >> /var/log/hipaa-setup.log
  EOF

  tags = { Name = "hipaa-elk-${var.environment}" }
}

variable "environment" { type = string }
variable "subnet_id" { type = string }
variable "security_group_id" { type = string }
variable "elk_security_group_id" { type = string }
variable "instance_type" { type = string }
variable "elk_instance_type" { type = string }
variable "key_name" { type = string }
variable "kms_key_arn" { type = string }

output "llm_private_ip" { value = aws_instance.llm.private_ip }
output "elk_private_ip" { value = aws_instance.elk.private_ip }
