"""飞书机器人一键收尾：校验应用凭据 + 算出事件订阅地址 + 在 cron-job.org 建保活任务。

前置：Render 上已用 render.yaml 蓝图部署好 timelyup-bot 服务（拿到 https://xxx.onrender.com）。
飞书的事件订阅地址没有 API 可写，需要把本脚本打印的 URL 手动粘贴到开发者后台。

用法（仓库根目录）:
    python tools/setup_feishu.py

凭据从 .secrets.local.json 读取（已 gitignore）:
    {
      "feishu_app_id": "cli_...",               // 开发者后台 → 凭证与基础信息
      "feishu_app_secret": "...",
      "bot_url": "https://timelyup-bot.onrender.com",
      "cronjob_api_key": "..."                  // 复用方案 B 的 key
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
FS_API = "https://open.feishu.cn/open-apis"
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
    app_id = sec.get("feishu_app_id", "").strip().strip("<>")
    app_secret = sec.get("feishu_app_secret", "").strip().strip("<>")
    bot_url = sec.get("bot_url", "").strip().strip("<>").rstrip("/")
    cj_key = sec.get("cronjob_api_key", "").strip().strip("<>")
    if not app_id.startswith("cli_"):
        raise SystemExit("请在 .secrets.local.json 填 feishu_app_id（开发者后台拿，形如 cli_...）")
    if not app_secret:
        raise SystemExit("请在 .secrets.local.json 填 feishu_app_secret")
    if not bot_url.startswith("https://"):
        raise SystemExit("请在 .secrets.local.json 填 bot_url（Render 服务地址，如 https://timelyup-bot.onrender.com）")

    # 1) 校验飞书应用凭据（取一次 tenant_access_token）
    status, body = _http("POST", f"{FS_API}/auth/v3/tenant_access_token/internal",
                         body={"app_id": app_id, "app_secret": app_secret})
    if status != 200 or not (isinstance(body, dict) and body.get("code") == 0):
        raise SystemExit(f"飞书凭据校验失败（{status}）：{str(body)[:300]}")
    print("✓ 飞书 App ID / Secret 有效")

    # 2) 服务可达性（免费档冷启动可能要等几十秒，失败就重试一次）
    status, body = _http("GET", f"{bot_url}/healthz")
    if status != 200:
        print(f"  /healthz 第一次返回 {status}（可能在冷启动），重试 ...")
        status, body = _http("GET", f"{bot_url}/healthz")
    if status != 200:
        raise SystemExit(f"/healthz 不可达（{status}）：确认 Render 服务已部署并 Live。{str(body)[:200]}")
    print(f"✓ 服务在线：{bot_url}")

    # 3) 事件订阅地址（路径由 app_secret 哈希派生，与 src/feishu_bot.py 同一算法）
    secret = hashlib.sha256(f"timelyup:{app_secret}".encode()).hexdigest()[:32]
    print("\n→ 把下面这个地址粘贴到 飞书开发者后台 → 事件与回调 → 事件订阅 → 请求地址：\n")
    print(f"   {bot_url}/fs/{secret}\n")
    print("   （保存时飞书会发 challenge 校验，服务在线即自动通过；Encrypt Key 留空，")
    print("    Verification Token 填到 Render 环境变量 FEISHU_VERIFICATION_TOKEN）")

    # 4) cron-job.org 保活任务（每 10 分钟 ping /healthz，防 Render 免费档休眠）
    if not cj_key:
        print("\n⚠ 未配置 cronjob_api_key，跳过保活任务——Render 免费档闲置 15 分钟会休眠，首条消息要等约 1 分钟冷启动")
        return
    cj_headers = {"Authorization": f"Bearer {cj_key}"}
    status, body = _http("GET", f"{CRONJOB_API}/jobs", cj_headers)
    if status != 200:
        raise SystemExit(f"cron-job.org API 校验失败（{status}）：{str(body)[:200]}")
    if KEEPALIVE_TITLE in {j.get("title") for j in body.get("jobs", [])}:
        print(f"\n  - 保活任务已存在，跳过：{KEEPALIVE_TITLE}")
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
        print(f"\n  - 已创建保活任务（jobId={body.get('jobId')}）")

    print("\n完成 ✅ 在开发者后台贴好事件订阅地址、发布版本后，给机器人发条消息试试："
          "未配置 ALLOWED_CHAT_IDS 时它会回你 chat_id，填进 Render 环境变量后即可正常对话。")


if __name__ == "__main__":
    main()
