import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum

import fastapi.responses
import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException, Request, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
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

# ─── User Management ────────────────────────────────────
USERS_FILE = Path(__file__).parent / ".users.json"
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Max file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".csv", ".doc", ".docx", ".json", ".xml", ".hl7"}


class Role(str, Enum):
    admin = "admin"
    provider = "provider"  # doctors, nurses — full access
    staff = "staff"  # front desk, billing — limited access
    readonly = "readonly"  # auditors — view only


ROLE_PERMISSIONS = {
    Role.admin: {"query", "upload", "analyze", "manage_users", "view_audit"},
    Role.provider: {"query", "upload", "analyze"},
    Role.staff: {"query"},
    Role.readonly: {"view_audit"},
}


def load_users() -> dict:
    if not USERS_FILE.exists():
        # Create default admin
        admin_key = secrets.token_urlsafe(32)
        admin_hash = hashlib.sha256(admin_key.encode()).hexdigest()
        users = {
            admin_hash: {
                "name": "Admin",
                "role": "admin",
                "created": datetime.now(timezone.utc).isoformat(),
                "active": True,
            }
        }
        USERS_FILE.write_text(json.dumps(users, indent=2))
        USERS_FILE.chmod(0o600)
        print(f"\n{'='*60}")
        print(f"Admin API key (save this — shown once):")
        print(f"  {admin_key}")
        print(f"{'='*60}\n")
        return users
    return json.loads(USERS_FILE.read_text())


def save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, indent=2))


users_db = load_users()


def verify_user(authorization: str | None) -> tuple[str, dict]:
    """Returns (key_id, user_dict) or raises."""
    if not authorization:
        raise HTTPException(status_code=401, detail="API key required")
    key = authorization.removeprefix("Bearer ").strip()
    hashed = hashlib.sha256(key.encode()).hexdigest()
    user = users_db.get(hashed)
    if not user or not user.get("active", True):
        raise HTTPException(status_code=403, detail="Invalid or deactivated API key")
    return hashed[:8], user


def check_permission(user: dict, permission: str):
    role = Role(user["role"])
    if permission not in ROLE_PERMISSIONS[role]:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role.value}' does not have '{permission}' permission",
        )


# ─── App Setup ───────────────────────────────────────────
app = FastAPI(
    title="SecureMed AI",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

OLLAMA_URL = config["ollama"]["base_url"]
MODEL = config["ollama"]["model"]
MAX_TOKENS = config["security"]["max_tokens"]


# ─── Models ──────────────────────────────────────────────
class QueryRequest(BaseModel):
    prompt: str
    system: str = "You are a helpful medical assistant. Never store or repeat patient identifiers unnecessarily."
    max_tokens: int = 2048


class CreateUserRequest(BaseModel):
    name: str
    role: Role


# ─── Routes ──────────────────────────────────────────────
@app.get("/")
async def root():
    return fastapi.responses.FileResponse(static_dir / "index.html")


@app.get("/pricing")
async def pricing_page():
    return fastapi.responses.FileResponse(static_dir / "pricing.html")


@app.post("/api/query")
async def query(
    request: QueryRequest,
    authorization: str | None = Header(default=None),
):
    key_id, user = verify_user(authorization)
    check_permission(user, "query")
    request_id = str(uuid.uuid4())[:8]
    tokens = min(request.max_tokens, MAX_TOKENS)

    audit_logger.info(
        f"REQUEST | id={request_id} | user={user['name']} | role={user['role']} | "
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
        "user": user["name"],
        "role": user["role"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Document Upload + Analysis ──────────────────────────
@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    action: str = Form(default="summarize"),
    authorization: str | None = Header(default=None),
):
    key_id, user = verify_user(authorization)
    check_permission(user, "upload")
    request_id = str(uuid.uuid4())[:8]

    # Validate file
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

    audit_logger.info(
        f"UPLOAD | id={request_id} | user={user['name']} | "
        f"filename_len={len(file.filename)} | size={len(content)} | type={ext} | action={action}"
    )

    # Extract text based on file type
    text = extract_text(content, ext)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    # Truncate to fit context window (Qwen 2.5 7B = 128K tokens, ~4 chars/token)
    max_chars = 100_000
    truncated = len(text) > max_chars
    text = text[:max_chars]

    # Build analysis prompt based on action
    prompts = {
        "summarize": f"Summarize the following medical document concisely. Highlight key findings, diagnoses, medications, and recommended actions:\n\n{text}",
        "extract": f"Extract all structured data from this medical document. List: patient demographics, diagnoses (with ICD codes if present), medications, procedures, lab results, and follow-up instructions:\n\n{text}",
        "risk": f"Analyze this medical document for potential risks, drug interactions, contraindications, or missing information that a clinician should be aware of:\n\n{text}",
        "letter": f"Based on this medical document, draft a professional referral letter summarizing the patient's condition, relevant history, and reason for referral:\n\n{text}",
        "billing": f"Review this medical document and identify all billable services, procedures, and diagnosis codes. Flag any documentation gaps that could affect reimbursement:\n\n{text}",
    }

    prompt = prompts.get(action, prompts["summarize"])

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "system": "You are a medical document analyst. Be thorough and precise. Never fabricate information not present in the document.",
                    "stream": False,
                    "options": {"num_predict": MAX_TOKENS},
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama is not running")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Model error")

    audit_logger.info(
        f"ANALYSIS | id={request_id} | action={action} | "
        f"input_chars={len(text)} | response_len={len(data.get('response', ''))}"
    )

    return {
        "id": request_id,
        "action": action,
        "response": data["response"],
        "document_chars": len(text),
        "truncated": truncated,
        "model": MODEL,
        "user": user["name"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def extract_text(content: bytes, ext: str) -> str:
    """Extract text from uploaded file. Handles common formats."""
    if ext == ".txt":
        return content.decode("utf-8", errors="replace")

    if ext == ".csv":
        return content.decode("utf-8", errors="replace")

    if ext == ".json":
        try:
            data = json.loads(content)
            return json.dumps(data, indent=2)
        except json.JSONDecodeError:
            return content.decode("utf-8", errors="replace")

    if ext == ".xml" or ext == ".hl7":
        return content.decode("utf-8", errors="replace")

    if ext == ".pdf":
        try:
            import pdfplumber
            import io
            text_parts = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except ImportError:
            return "[PDF support requires pdfplumber: pip install pdfplumber]"
        except Exception as e:
            return f"[PDF extraction error: {e}]"

    if ext in (".doc", ".docx"):
        try:
            import docx
            import io
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return "[DOCX support requires python-docx: pip install python-docx]"
        except Exception as e:
            return f"[DOCX extraction error: {e}]"

    return content.decode("utf-8", errors="replace")


# ─── User Management (Admin Only) ────────────────────────
@app.post("/api/users")
async def create_user(
    request: CreateUserRequest,
    authorization: str | None = Header(default=None),
):
    key_id, admin = verify_user(authorization)
    check_permission(admin, "manage_users")

    new_key = secrets.token_urlsafe(32)
    new_hash = hashlib.sha256(new_key.encode()).hexdigest()

    users_db[new_hash] = {
        "name": request.name,
        "role": request.role.value,
        "created": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }
    save_users(users_db)

    audit_logger.info(
        f"USER_CREATED | by={admin['name']} | new_user={request.name} | role={request.role.value}"
    )

    return {
        "name": request.name,
        "role": request.role.value,
        "api_key": new_key,
        "message": "Save this API key — it cannot be retrieved later",
    }


@app.get("/api/users")
async def list_users(authorization: str | None = Header(default=None)):
    key_id, admin = verify_user(authorization)
    check_permission(admin, "manage_users")

    return [
        {"name": u["name"], "role": u["role"], "active": u["active"], "created": u["created"]}
        for u in users_db.values()
    ]


@app.delete("/api/users/{username}")
async def deactivate_user(
    username: str,
    authorization: str | None = Header(default=None),
):
    key_id, admin = verify_user(authorization)
    check_permission(admin, "manage_users")

    for key_hash, user in users_db.items():
        if user["name"] == username:
            user["active"] = False
            save_users(users_db)
            audit_logger.info(f"USER_DEACTIVATED | by={admin['name']} | user={username}")
            return {"message": f"User '{username}' deactivated"}

    raise HTTPException(status_code=404, detail=f"User '{username}' not found")


# ─── Audit Log Access ────────────────────────────────────
@app.get("/api/audit")
async def get_audit_log(
    lines: int = 50,
    authorization: str | None = Header(default=None),
):
    key_id, user = verify_user(authorization)
    check_permission(user, "view_audit")

    log_path = Path(config["logging"]["audit_log"])
    if not log_path.exists():
        return {"entries": []}

    all_lines = log_path.read_text().strip().split("\n")
    recent = all_lines[-lines:]
    return {"entries": recent, "total": len(all_lines)}


# ─── Health ──────────────────────────────────────────────
@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"status": "healthy", "models": models, "product": "SecureMed AI"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": "Cannot reach Ollama"},
        )


if __name__ == "__main__":
    import uvicorn

    print(f"\n  SecureMed AI")
    print(f"  {'─'*40}")
    print(f"  Server:    http://{config['server']['host']}:{config['server']['port']}")
    print(f"  Model:     {MODEL}")
    print(f"  Audit log: {config['logging']['audit_log']}")
    print(f"  Uploads:   {UPLOAD_DIR}")
    print()
    uvicorn.run(
        app,
        host=config["server"]["host"],
        port=config["server"]["port"],
        log_level="warning",
    )
