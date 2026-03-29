# HIPAA-Compliant Private LLM

A locally-hosted LLM setup using Ollama + Qwen 2.5, designed for HIPAA-compliant medical data processing. No data ever leaves your machine.

## Architecture

```
[Client] --> [localhost:11434] --> [Ollama + Qwen 2.5 7B]
                                       |
                                  [Local Storage Only]
                                  [No External API Calls]
```

## Why This Is HIPAA-Compliant

- **No cloud dependency** — model runs 100% locally via Ollama
- **No data egress** — PHI never leaves the machine
- **No third-party APIs** — unlike ChatGPT/Claude, no BAA needed for the LLM itself
- **Audit logging** — all queries logged locally with timestamps
- **Access control** — binds to localhost only by default

## Quick Start

### Prerequisites
- macOS with Apple Silicon (M1+) or Linux
- 16GB+ RAM
- Homebrew (macOS)

### Install

```bash
# Install Ollama
brew install ollama

# Start the service
brew services start ollama

# Pull the model
ollama pull qwen2.5:7b
```

### Run the API Server

```bash
# Install dependencies
pip install -r requirements.txt

# Start the HIPAA-compliant API
python server.py
```

The server runs at `http://localhost:8080` with:
- Request/response audit logging
- No external network calls
- Input sanitization

### Test It

```bash
curl -X POST http://localhost:8080/api/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize HIPAA Privacy Rule requirements"}'
```

## HIPAA Compliance Checklist

| Requirement | Status | Implementation |
|------------|--------|---------------|
| Data at rest encryption | Required | Enable FileVault (macOS) or LUKS (Linux) |
| Data in transit encryption | N/A | Localhost only — no network transit |
| Access controls | Included | API key auth, localhost binding |
| Audit logging | Included | All queries logged to `logs/audit.log` |
| No data egress | Included | Model runs fully offline |
| BAA with LLM provider | N/A | No third-party LLM provider |

## Configuration

Edit `config.yaml` to customize:

```yaml
server:
  host: "127.0.0.1"  # localhost only — do NOT change to 0.0.0.0
  port: 8080

ollama:
  model: "qwen2.5:7b"
  base_url: "http://127.0.0.1:11434"

logging:
  audit_log: "logs/audit.log"
  level: "INFO"

security:
  api_key_required: true
  max_tokens: 4096
```

## Important Notes

- **Do NOT expose port 8080 or 11434 to the internet**
- Enable full-disk encryption on your machine
- Rotate API keys regularly
- Review audit logs periodically
- This setup handles the LLM component — you still need compliant practices for data storage, user authentication, and organizational policies
