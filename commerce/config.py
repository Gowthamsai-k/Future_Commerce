import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DB_NAME = os.getenv("DB_NAME", str(ROOT_DIR / "gaming_store.db"))
MCP_HOST = os.getenv("HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("PORT", "8000"))
AI_API_HOST = os.getenv("AI_API_HOST", "0.0.0.0")
AI_API_PORT = int(os.getenv("AI_API_PORT", "9000"))
MCP_URL = os.getenv("MCP_URL", f"http://127.0.0.1:{MCP_PORT}/sse")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-mini")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
AUDIT_FILE = Path(os.getenv("BUYER_AUDIT_FILE", str(ROOT_DIR / "buyer_audit.jsonl")))
