import os
from dotenv import load_dotenv

load_dotenv()

# Server config
BRIDGE_HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")
try:
    BRIDGE_PORT = int(os.getenv("BRIDGE_PORT", "8001"))
except ValueError:
    BRIDGE_PORT = 8001
BRIDGE_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

# CORS (GitHub Pages)
ALLOWED_ORIGINS = [
    "https://ksasao.github.io",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Ollama
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

# External AI (optional)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Session storage
SESSIONS_STORAGE = os.path.join(os.path.dirname(__file__), "sessions")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
