"""加载配置：config.yaml + 工作背景 + 环境变量。"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EPISODES_DIR = DOCS / "episodes"


def _load_profile() -> str:
    """工作背景读取优先级：
    1. 环境变量 WORK_PROFILE（线上用 GitHub 加密 Secret 注入，保密）
    2. profile.local.md（本地私有文件，已 gitignore，不会提交）
    3. profile.md（公开仓库里的通用模板）
    """
    env_profile = os.environ.get("WORK_PROFILE", "").strip()
    if env_profile:
        return env_profile
    for fname in ("profile.local.md", "profile.md"):
        p = ROOT / fname
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 环境变量（GitHub Actions 注入 / 本地手动设置）
    cfg["env"] = {
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        # 用 `or`：环境变量未设或为空字符串时都回退到默认（GitHub 未设变量会注入空串）
        "gemini_model": os.environ.get("GEMINI_MODEL") or cfg.get("ai", {}).get("model") or "gemini-2.5-flash",
        # 播客对外访问的根地址，例如 https://用户名.github.io/timelyUP
        "base_url": os.environ.get("PAGES_BASE_URL", "").rstrip("/"),
    }
    cfg["profile"] = _load_profile()
    return cfg
