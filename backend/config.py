from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "15"))
    _configured_gemini_key: str = os.getenv("GEMINI_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "") or (_configured_gemini_key if _configured_gemini_key.startswith("gsk_") else "")
    gemini_api_key: str = "" if _configured_gemini_key.startswith(("sk-or-", "gsk_")) else _configured_gemini_key
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "") or (_configured_gemini_key if _configured_gemini_key.startswith("sk-or-") else "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    groq_vision_model: str = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    data_dir: Path = ROOT / "data"

settings = Settings()
settings.data_dir.joinpath("uploads").mkdir(parents=True, exist_ok=True)
settings.data_dir.joinpath("database").mkdir(parents=True, exist_ok=True)
