"""方案 B 一键配置：在 cron-job.org 创建两个定点任务，按北京时间调 GitHub workflow_dispatch。

用法（在仓库根目录）:
    python tools/setup_cronjob.py            # 创建/核对两个定时任务（可重复运行，已存在则跳过）
    python tools/setup_cronjob.py --test     # 额外手动触发一次 dispatch，端到端验证链路

凭据从仓库根 .secrets.local.json 读取（已 gitignore，不会进仓库）:
    {
      "github_pat": "github_pat_xxx",     // 细粒度 PAT：仅 timelyUP 仓库，仅 Actions: Read and write
      "cronjob_api_key": "xxx"            // cron-job.org 控制台 Settings → API 创建
    }
也可用环境变量 GH_PAT / CRONJOB_API_KEY 覆盖。

定时点（Asia/Shanghai）：早报 06:40、晚报 17:40——生成约 10 分钟，赶在 07:00 通勤 / 18:00 下班前。
GitHub 仓库里的 schedule 三拍保留作兜底，pipeline 判重保证两路只出一集。
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO = "Juliecode/timelyUP"
WORKFLOW = "daily.yml"
CRONJOB_API = "https://api.cron-job.org"
SECRETS_FILE = Path(__file__).resolve().parent.parent / ".secrets.local.json"

# (任务标题, slot, 北京时间 时, 分)
JOBS = [
    ("timelyUP 早报 06:40 (北京)", "am", 6, 40),
    ("timelyUP 晚报 17:40 (北京)", "pm", 17, 40),
]


def _http(method: str, url: str, headers: dict, body: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip().startswith("{") else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def load_secrets() -> tuple[str, str]:
    pat = os.environ.get("GH_PAT", "").strip()
    key = os.environ.get("CRONJOB_API_KEY", "").strip()
    if SECRETS_FILE.exists():
        data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        pat = pat or data.get("github_pat", "").strip()
        key = key or data.get("cronjob_api_key", "").strip()
    missing = [n for n, v in (("github_pat", pat), ("cronjob_api_key", key)) if not v or v.startswith("<")]
    if missing:
        raise SystemExit(f"缺少凭据 {missing}：请填写 {SECRETS_FILE} 或设置环境变量 GH_PAT/CRONJOB_API_KEY")
    return pat, key


def gh_headers(pat: str) -> dict:
    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "timelyUP-setup",
        "Content-Type": "application/json",
    }


def check_pat(pat: str) -> None:
    status, body = _http("GET", f"https://api.github.com/repos/{REPO}", gh_headers(pat))
    if status != 200:
        raise SystemExit(f"PAT 校验失败（GET repo 返回 {status}）：{str(body)[:200]}")
    print(f"✓ PAT 可访问 {REPO}")


def dispatch(pat: str, slot: str) -> None:
    status, body = _http(
        "POST",
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
        gh_headers(pat),
        {"ref": "main", "inputs": {"slot": slot}},
    )
    if status != 204:
        raise SystemExit(f"dispatch 失败（{status}）：{str(body)[:300]}。"
                         "常见原因：PAT 没有该仓库的 Actions: Read and write 权限。")
    print(f"✓ 已触发一次 dispatch（slot={slot}，未带 force，已生成则会自动跳过）")


def setup_jobs(pat: str, api_key: str) -> None:
    cj_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    status, body = _http("GET", f"{CRONJOB_API}/jobs", cj_headers)
    if status != 200:
        raise SystemExit(f"cron-job.org API key 校验失败（{status}）：{str(body)[:200]}")
    existing = {j.get("title") for j in body.get("jobs", [])}
    print(f"✓ cron-job.org API 可用，现有任务 {len(existing)} 个")

    for title, slot, hour, minute in JOBS:
        if title in existing:
            print(f"  - 已存在，跳过：{title}")
            continue
        job = {
            "job": {
                "title": title,
                "url": f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
                "enabled": True,
                "saveResponses": True,
                "requestMethod": 1,  # POST
                "extendedData": {
                    "headers": gh_headers(pat),
                    "body": json.dumps({"ref": "main", "inputs": {"slot": slot}}),
                },
                "schedule": {
                    "timezone": "Asia/Shanghai",
                    "expiresAt": 0,
                    "hours": [hour],
                    "minutes": [minute],
                    "mdays": [-1],
                    "months": [-1],
                    "wdays": [-1],
                },
            }
        }
        status, body = _http("PUT", f"{CRONJOB_API}/jobs", cj_headers, job)
        if status != 200:
            raise SystemExit(f"创建任务失败（{status}）：{str(body)[:300]}")
        print(f"  - 已创建：{title}（jobId={body.get('jobId')}）")


def main() -> None:
    pat, api_key = load_secrets()
    check_pat(pat)
    setup_jobs(pat, api_key)
    if "--test" in sys.argv:
        dispatch(pat, "pm" if "--pm" in sys.argv else "am")
    print("\n完成 ✅ 可在 https://console.cron-job.org 查看任务与执行历史（GitHub 接受请求返回 204）。")


if __name__ == "__main__":
    main()
