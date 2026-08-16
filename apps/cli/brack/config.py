"""
Brack CLI — Configuration management.
Stores settings in ~/.brack/config.json
"""
import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


CONFIG_DIR = Path.home() / ".brack"
CONFIG_FILE = CONFIG_DIR / "config.json"


class BrackConfig(BaseModel):
    api_url: str = "http://localhost:8000"
    username: Optional[str] = None
    token: Optional[str] = None


def load_config() -> BrackConfig:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return BrackConfig(**data)
        except Exception:
            pass
    return BrackConfig()


def save_config(config: BrackConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(config.model_dump_json(indent=2))
    # Restrict file permissions (Unix only)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass


def get_api_url() -> str:
    return load_config().api_url


def get_auth_headers() -> dict:
    config = load_config()
    if config.token:
        return {"Authorization": f"Bearer {config.token}"}
    return {}
