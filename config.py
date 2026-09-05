import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    # LLM Credentials
    API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    CUSTOM_MODEL_BASE_URL: str = os.getenv("CUSTOM_MODEL_BASE_URL", "")
    CUSTOM_MODEL_API_KEY: str = os.getenv("CUSTOM_MODEL_API_KEY", "EMPTY")

    # Dashboard Authentication & Network
    DASHBOARD_API_KEY: str = os.getenv("DASHBOARD_API_KEY", os.getenv("AGENT_API_TOKEN", "change-me-in-production"))
    AGENT_API_TOKEN: str = os.getenv("AGENT_API_TOKEN", os.getenv("DASHBOARD_API_KEY", "change-me-in-production"))
    DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8000"))
    DASHBOARD_BASE_URL: str = os.getenv("DASHBOARD_BASE_URL", "http://127.0.0.1:8000")

    # Execution Parameters
    MODEL_NAME: str = os.getenv("MODEL_NAME", os.getenv("AGENT_MODEL_NAME", "gpt-4o-mini"))
    HEARTBEAT_INTERVAL_SECONDS: int = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))
    MAX_CONSECUTIVE_FAILURES: int = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "5"))
    MAX_CONCURRENT_TOOL_CALLS: int = int(os.getenv("MAX_CONCURRENT_TOOL_CALLS", "5"))
    DB_PATH: str = os.getenv("DB_PATH", os.getenv("AGENT_DB_PATH", "agent_state.db"))

    # Evolutionary Island & Sandbox Configuration
    NUM_ISLANDS: int = int(os.getenv("NUM_ISLANDS", "4"))
    EVALS_PER_ISLAND: int = int(os.getenv("EVALS_PER_ISLAND", "25"))
    MAX_CLUSTERS_PER_ISLAND: int = int(os.getenv("MAX_CLUSTERS_PER_ISLAND", "12"))
    WASM_FUEL_BUDGET: int = int(os.getenv("WASM_FUEL_BUDGET", "2000000"))
    SANDBOX_TIMEOUT_SEC: float = float(os.getenv("SANDBOX_TIMEOUT_SEC", os.getenv("GVISOR_TIMEOUT_SECONDS", "4.0")))
    GVISOR_TIMEOUT_SECONDS: float = float(os.getenv("SANDBOX_TIMEOUT_SEC", os.getenv("GVISOR_TIMEOUT_SECONDS", "4.0")))
    LEAN_BIN_PATH: str = os.getenv("LEAN_BIN_PATH", "lean")

    # Scheduler Defaults
    NIGHTLY_DISCOVERY_CRON: str = os.getenv("NIGHTLY_DISCOVERY_CRON", "0 2 * * *")
    AUTO_PR_FITNESS_THRESHOLD: float = float(os.getenv("AUTO_PR_FITNESS_THRESHOLD", "0.88"))

    # Security Reconnaissance & Audit
    SECURITY_SCAN_ALLOWED_HOSTS: List[str] = field(
        default_factory=lambda: [
            h.strip()
            for h in os.getenv("SECURITY_SCAN_ALLOWED_HOSTS", "localhost,127.0.0.1,testphp.vulnweb.com").split(",")
            if h.strip()
        ]
    )
    ZAP_BASE_URL: str = os.getenv("ZAP_BASE_URL", "http://localhost:8080")
    ZAP_API_KEY: str = os.getenv("ZAP_API_KEY", "")

    # Notifications
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # GitOps Automation
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "owner/repo")
    GITHUB_BASE_BRANCH: str = os.getenv("GITHUB_BASE_BRANCH", "main")

config = Settings()
