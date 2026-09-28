import os
from pathlib import Path
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings(BaseModel):
    # LLM Settings
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini").lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1")

    # Decision Engine (Jev by TypeSafe AI)
    typesafe_api_key: str = os.getenv("TYPESAFE_API_KEY", "")
    jev_model: str = os.getenv("JEV_MODEL", "jev-1.13.0")
    jev_mock: bool = os.getenv("JEV_MOCK", "true").lower() in ("true", "1", "yes")
    jev_base_url: str = os.getenv("JEV_BASE_URL", "")

    # Pricing per 1M tokens ($0.042)
    jev_cost_per_million_tokens: float = 0.042

    # Low-Confidence & Workload Thresholds
    min_confidence: float = float(os.getenv("MIN_CONFIDENCE", "0.60"))
    tie_margin: float = float(os.getenv("TIE_MARGIN", "0.05"))
    high_burnout_prob: float = float(os.getenv("HIGH_BURNOUT_PROB", "0.70"))

    # Ranking Weights
    weight_skill: float = float(os.getenv("WEIGHT_SKILL", "0.35"))
    weight_availability: float = float(os.getenv("WEIGHT_AVAILABILITY", "0.25"))
    weight_burnout: float = float(os.getenv("WEIGHT_BURNOUT", "0.20"))
    weight_seniority: float = float(os.getenv("WEIGHT_SENIORITY", "0.15"))
    weight_cost: float = float(os.getenv("WEIGHT_COST", "0.05"))

    # Server & Database
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    db_path: Path = BASE_DIR / "staffing.db"

settings = Settings()
