"""交互机器人一键收尾：注册 Telegram webhook + 在 cron-job.org 建保活任务。

前置：Render 上已用 render.yaml 蓝图部署好 timelyup-bot 服务（拿到 https://xxx.onrender.com）。

用法（仓库根目录）:
    python tools/setup_telegram.py

凭据从 .secrets.local.json 读取（已 gitignore）:
    {
      "telegram_bot_token": "123456:ABC...",   // BotFather 发的
      "bot_url": "https://timelyup-bot.onrender.com",
      "cronjob_api_key": "..."                 // 复用方案 B 的 key
    }
"""
import hashlib
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

CRONJOB_API = "https://api.cron-job.org"
SECRETS_FILE = Path(__file__).resolve().parent.parent / ".secrets.local.json"
KEEPALIVE_TITLE = "timelyUP bot 保活 (每10分钟)"


def _http(method: str, url: str, headers: dict | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip().startswith("{") else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> None:
    if not SECRETS_FILE.exists():
        raise SystemExit(f"找不到 {SECRETS_FILE}")
    sec = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    token = sec.get("telegram_bot_token", "").strip().strip("<>")
    bot_url = sec.get("bot_url", "").strip().strip("<>").rstrip("/")
    cj_key = sec.get("cronjob_api_key", "").strip().strip("<>")
    if not token or ":" not in token:
        raise SystemExit("请在 .secrets.local.json 填 telegram_bot_token（BotFather 发的，形如 123456:ABC...）")
    if not bot_url.startswith("https://"):
        raise SystemExit("请在 .secrets.local.json 填 bot_url（Render 服务地址，如 https://timelyup-bot.onrender.com）")

    # 1) 服务可达性（免费档冷启动可能要等几十秒，失败就重试一次）
    status, body = _http("GET", f"{bot_url}/healthz")
    if status != 200:
        print(f"  /healthz 第一次返回 {status}（可能在冷启动），重试 ...")
        status, body = _http("GET", f"{bot_url}/healthz")
    if status != 200:
        raise SystemExit(f"/healthz 不可达（{status}）：确认 Render 服务已部署并 Live。{str(body)[:200]}")
    print(f"✓ 服务在线：{bot_url}")

    # 2) 注册 webhook（路径与 secret_token 都由 token 哈希派生，与 src/bot.py 同一算法）
    secret = hashlib.sha256(f"timelyup:{token}".encode()).hexdigest()[:32]
    status, body = _http("POST", f"https://api.telegram.org/bot{token}/setWebhook", body={
        "url": f"{bot_url}/tg/{secret}",
        "secret_token": secret,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    })
    if status != 200 or not (isinstance(body, dict) and body.get("ok")):
        raise SystemExit(f"setWebhook 失败（{status}）：{str(body)[:300]}")
    print("✓ webhook 已注册")

    # 3) cron-job.org 保活任务（每 10 分钟 ping /healthz，防 Render 免费档休眠）
    if not cj_key:
        print("⚠ 未配置 cronjob_api_key，跳过保活任务——Render 免费档闲置 15 分钟会休眠，首条消息要等约 1 分钟冷启动")
        return
    cj_headers = {"Authorization": f"Bearer {cj_key}"}
    status, body = _http("GET", f"{CRONJOB_API}/jobs", cj_headers)
    if status != 200:
        raise SystemExit(f"cron-job.org API 校验失败（{status}）：{str(body)[:200]}")
    if KEEPALIVE_TITLE in {j.get("title") for j in body.get("jobs", [])}:
        print(f"  - 保活任务已存在，跳过：{KEEPALIVE_TITLE}")
    else:
        status, body = _http("PUT", f"{CRONJOB_API}/jobs", cj_headers, {
            "job": {
                "title": KEEPALIVE_TITLE,
                "url": f"{bot_url}/healthz",
                "enabled": True,
                "saveResponses": False,
                "requestMethod": 0,  # GET
                "schedule": {"timezone": "Asia/Shanghai", "expiresAt": 0,
                             "hours": [-1], "minutes": [0, 10, 20, 30, 40, 50],
                             "mdays": [-1], "months": [-1], "wdays": [-1]},
            }
        })
        if status != 200:
            raise SystemExit(f"创建保活任务失败（{status}）：{str(body)[:300]}")
        print(f"  - 已创建保活任务（jobId={body.get('jobId')}）")

    print("\n完成 ✅ 给机器人发条消息试试：未配置 ALLOWED_CHAT_IDS 时它会回你 chat_id，"
          "把它填进 Render 环境变量后即可正常对话。")


if __name__ == "__main__":
    main()
