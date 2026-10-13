"""Centralized environment loading and project paths."""
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

def load_project_env() -> None:
    # Explicit path avoids depending on the terminal's current working directory.
    load_dotenv(dotenv_path=ENV_FILE, override=True)

def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)

load_project_env()
