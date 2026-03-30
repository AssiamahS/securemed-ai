# SecureMed AI — Compliance & Responsibility Framework

## What SecureMed Is

SecureMed AI is a **HIPAA-supporting reference architecture** for deploying private,
self-hosted AI in healthcare environments. It provides the technical controls —
encryption, access control, audit logging, PHI redaction, and network isolation —
that support an organization's HIPAA compliance program.

## What SecureMed Is NOT

SecureMed is not a complete HIPAA compliance solution by itself. HIPAA compliance
requires a combination of technical, administrative, and physical safeguards that
extend beyond any single software tool.

## Client Responsibilities

The following remain the deploying organization's responsibility:

### Administrative Safeguards
- Written HIPAA policies and procedures
- Workforce training on PHI handling
- Designated Privacy Officer and Security Officer
- Risk assessment documentation (required annually)
- Incident response and breach notification procedures
- Business Associate Agreements (BAAs) with all vendors that handle PHI
  - If deployed on AWS: activate BAA via AWS Artifact
  - SecureMed itself does not require a BAA (self-hosted, no third-party PHI access)

### Physical Safeguards
- Physical security of servers (if on-premise)
- Workstation security policies
- Device and media disposal procedures

### Organizational Requirements
- Documentation of compliance efforts
- Periodic audits and reviews
- Staff sanctions for policy violations

## What SecureMed Provides (Technical Safeguards)

| HIPAA Requirement | SecureMed Implementation |
|-------------------|--------------------------|
| Access Controls (§164.312(a)) | Role-based access: admin, provider, staff, readonly. API key authentication with SHA-256 hashing. |
| Audit Controls (§164.312(b)) | Every query, upload, user action, and PHI redaction logged with timestamp, user, and role. PHI content never logged. |
| Integrity Controls (§164.312(c)) | Input validation, file type restrictions, max upload size. |
| Transmission Security (§164.312(e)) | Localhost-only binding. VPC private subnet deployment. No public endpoints. |
| Encryption at Rest (§164.312(a)(2)(iv)) | AWS KMS encryption for all EBS volumes. |
| PHI Minimum Necessary | PHI redaction microservice strips identifiers before LLM processing. Audit logs record metadata only. |
| Emergency Access | Terraform IaC enables full infrastructure rebuild from code. |

## Deployment Models

### On-Premise (Clinic Install)
- AI runs on hardware physically located in the clinic
- Zero internet dependency — fully air-gapped operation possible
- All data stays within the organization's physical control
- No BAA required with any third party for the LLM component

### Private Cloud (AWS/VPS)
- Deployed in a BAA-covered AWS account (client activates via AWS Artifact)
- Private subnet only — no public IP, no inbound internet access
- Encrypted EBS storage via AWS KMS with automatic key rotation
- VPC flow logs and CloudTrail for network and API audit trails
- Access restricted to client's IP range via security groups

## PHI Handling

### Pre-Processing (PHI Redactor)
All documents pass through a PHI redaction microservice before reaching the LLM.
The redactor identifies and strips the 18 HIPAA identifiers:
- Names, dates, phone/fax, email, SSN, MRN, insurance IDs
- Geographic data, account numbers, URLs, IP addresses
- Device/vehicle identifiers, license numbers

### Audit Logging
Logs record:
- WHO: user name, role, API key prefix
- WHAT: action type (query, upload, template run, user management)
- WHEN: ISO 8601 timestamp
- HOW MUCH: input length, output length, processing time

Logs never record:
- Prompt content (may contain PHI)
- Response content (may contain PHI)
- Uploaded file contents
- Patient identifiers
