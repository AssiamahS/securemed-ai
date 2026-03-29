import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Load config
config_path = Path(__file__).parent / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# Setup audit logging
log_dir = Path(config["logging"]["audit_log"]).parent
log_dir.mkdir(parents=True, exist_ok=True)

audit_logger = logging.getLogger("hipaa_audit")
audit_logger.setLevel(config["logging"]["level"])
handler = logging.FileHandler(config["logging"]["audit_log"])
handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
audit_logger.addHandler(handler)

# API key management
API_KEYS_FILE = Path(__file__).parent / ".api_keys"


def load_api_keys() -> set[str]:
    if not API_KEYS_FILE.exists():
        key = secrets.token_urlsafe(32)
        hashed = hashlib.sha256(key.encode()).hexdigest()
        API_KEYS_FILE.write_text(hashed + "\n")
        API_KEYS_FILE.chmod(0o600)
        print(f"\n{'='*60}")
        print(f"Generated API key (save this — it won't be shown again):")
        print(f"  {key}")
        print(f"{'='*60}\n")
        return {hashed}
    return {line.strip() for line in API_KEYS_FILE.read_text().splitlines() if line.strip()}


api_key_hashes = load_api_keys()

app = FastAPI(
    title="HIPAA-Compliant LLM API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

OLLAMA_URL = config["ollama"]["base_url"]
MODEL = config["ollama"]["model"]
MAX_TOKENS = config["security"]["max_tokens"]


class QueryRequest(BaseModel):
    prompt: str
    system: str = "You are a helpful medical assistant. Never store or repeat patient identifiers unnecessarily."
    max_tokens: int = 2048


def verify_api_key(authorization: str | None) -> str:
    if not config["security"]["api_key_required"]:
        return "no-auth"
    if not authorization:
        raise HTTPException(status_code=401, detail="API key required")
    key = authorization.removeprefix("Bearer ").strip()
    hashed = hashlib.sha256(key.encode()).hexdigest()
    if hashed not in api_key_hashes:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return hashed[:8]


@app.post("/api/query")
async def query(
    request: QueryRequest,
    authorization: str | None = Header(default=None),
):
    key_id = verify_api_key(authorization)
    request_id = str(uuid.uuid4())[:8]
    tokens = min(request.max_tokens, MAX_TOKENS)

    # Audit log — never log the actual prompt content (PHI risk)
    audit_logger.info(
        f"REQUEST | id={request_id} | key={key_id} | "
        f"prompt_len={len(request.prompt)} | max_tokens={tokens}"
    )

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "prompt": request.prompt,
                    "system": request.system,
                    "stream": False,
                    "options": {"num_predict": tokens},
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.ConnectError:
        audit_logger.error(f"OLLAMA_DOWN | id={request_id}")
        raise HTTPException(status_code=503, detail="Ollama is not running")
    except httpx.HTTPStatusError as e:
        audit_logger.error(f"OLLAMA_ERROR | id={request_id} | status={e.response.status_code}")
        raise HTTPException(status_code=502, detail="Model error")

    audit_logger.info(
        f"RESPONSE | id={request_id} | "
        f"response_len={len(data.get('response', ''))} | "
        f"eval_duration_ms={data.get('eval_duration', 0) // 1_000_000}"
    )

    return {
        "id": request_id,
        "response": data["response"],
        "model": MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"status": "healthy", "models": models}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": "Cannot reach Ollama"},
        )


if __name__ == "__main__":
    import uvicorn

    print(f"Starting HIPAA-compliant LLM server on {config['server']['host']}:{config['server']['port']}")
    print(f"Model: {MODEL}")
    print(f"Audit log: {config['logging']['audit_log']}")
    uvicorn.run(
        app,
        host=config["server"]["host"],
        port=config["server"]["port"],
        log_level="warning",
    )
