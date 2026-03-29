# HIPAA-Compliant Private LLM for Clinics

One-click HIPAA-compliant infrastructure: private LLM (Ollama + Qwen), ELK monitoring, Terraform IaC, and GitHub CI/CD.

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │           AWS VPC (Private)              │
                        │                                          │
  Clinic Staff ──VPN──> │  ┌─────────────┐    ┌────────────────┐  │
                        │  │ LLM Server  │    │  ELK Monitor   │  │
                        │  │             │    │                │  │
                        │  │ Ollama      │───>│ Elasticsearch  │  │
                        │  │ Qwen 2.5    │    │ Logstash       │  │
                        │  │ FastAPI     │    │ Kibana         │  │
                        │  │ Filebeat    │    │                │  │
                        │  └─────────────┘    └────────────────┘  │
                        │                                          │
                        │  KMS Encryption | CloudTrail | VPC Logs  │
                        └─────────────────────────────────────────┘
```

## What's Included

| Component | Purpose | HIPAA Role |
|-----------|---------|------------|
| **Terraform** | One-command infrastructure deployment | Reproducible, auditable infrastructure |
| **Ollama + Qwen 2.5** | Private LLM — no data leaves your network | Zero PHI egress |
| **ELK Stack** | Centralized logging and monitoring | Audit trail, anomaly detection |
| **GitHub Actions** | CI/CD with security scanning | Automated compliance checks |
| **AWS KMS** | Encryption at rest | HIPAA encryption requirement |
| **CloudTrail** | API audit logging | HIPAA audit requirement |
| **VPC Flow Logs** | Network traffic monitoring | HIPAA access monitoring |

## Quick Start

### Local Development (Your Mac)

```bash
# Install Ollama + Qwen
brew install ollama
brew services start ollama
ollama pull qwen2.5:7b

# Run the API
pip install -r requirements.txt
python server.py
```

### Production Deployment (AWS)

```bash
# 1. Configure
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your clinic's IP and AWS key

# 2. Preview
terraform init
terraform plan

# 3. Deploy
terraform apply
```

This creates:
- Private VPC with no public-facing resources
- LLM server (t3.xlarge, 16GB RAM) with encrypted EBS
- ELK monitoring server with 100GB encrypted storage
- KMS encryption, CloudTrail audit, VPC flow logs
- Security groups locked to your clinic's IP only

### Test the API

```bash
curl -X POST http://localhost:8080/api/query \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize HIPAA Privacy Rule requirements"}'
```

## Project Structure

```
hippa/
├── server.py                    # FastAPI LLM API with audit logging
├── config.yaml                  # Server configuration
├── requirements.txt             # Python dependencies
├── terraform/
│   ├── main.tf                  # Root module — orchestrates everything
│   ├── variables.tf             # Input variables
│   ├── outputs.tf               # Output values
│   ├── terraform.tfvars.example # Template for your config
│   └── modules/
│       ├── networking/          # VPC, subnets, NAT, flow logs
│       ├── security/            # KMS, security groups, CloudTrail
│       └── compute/             # EC2 instances (LLM + ELK)
├── docker/
│   └── elk/
│       ├── docker-compose.yml   # ELK stack (Elasticsearch, Logstash, Kibana)
│       ├── .env.example         # ELK passwords template
│       └── logstash/pipeline/
│           └── hipaa.conf       # Log parsing + PHI scrubbing
└── .github/
    └── workflows/
        └── deploy.yml           # CI/CD: security scan → plan → apply
```

## HIPAA Compliance Matrix

| Requirement | Implementation | Status |
|------------|---------------|--------|
| Encryption at rest | AWS KMS + encrypted EBS volumes | Included |
| Encryption in transit | VPC-internal only, TLS available | Included |
| Access controls | Security groups, API keys, VPN-only access | Included |
| Audit logging | CloudTrail + ELK + application audit logs | Included |
| PHI data scrubbing | Logstash pipeline redacts SSN/email/phone from logs | Included |
| Network monitoring | VPC Flow Logs to CloudWatch | Included |
| Backup & recovery | `terraform apply` rebuilds entire infrastructure | Included |
| BAA with cloud provider | AWS BAA available via AWS Artifact | Required |
| Minimum necessary access | Private subnets, clinic-IP-only security groups | Included |

## CI/CD Pipeline

Every push to `main` triggers:

1. **Security Scan** — TruffleHog (secrets), tfsec (Terraform misconfigs), port binding check
2. **Terraform Plan** — preview infrastructure changes (on PRs)
3. **Terraform Apply** — deploy to AWS (on merge, requires manual approval)
4. **API Tests** — verify security defaults in config

## ELK Monitoring

The ELK stack collects and monitors:

- **LLM audit logs** — every query (prompt length, not content), response times, API key usage
- **Linux auditd** — system-level access tracking
- **System logs** — syslog for security events
- **PHI scrubbing** — Logstash automatically redacts SSN, email, and phone patterns from all logs

Access Kibana via SSH tunnel:
```bash
ssh -L 5601:elk-private-ip:5601 ubuntu@bastion
# Then open http://localhost:5601
```

## Security Notes

- All resources are in private subnets — no public IPs
- Security groups restrict access to your clinic's IP range only
- IMDSv2 required on all instances (prevents SSRF attacks)
- KMS key rotation enabled automatically
- CloudTrail logs are encrypted and versioned in S3
- ELK ports bound to `127.0.0.1` only inside Docker
- The LLM API never logs prompt content (PHI risk)
- API keys are stored as SHA-256 hashes

## Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| t3.xlarge (LLM) | ~$120 |
| t3.large (ELK) | ~$60 |
| NAT Gateway | ~$32 |
| EBS Storage (150GB) | ~$12 |
| CloudTrail + S3 | ~$5 |
| **Total** | **~$229/mo** |

Destroy everything when not in use: `terraform destroy`
