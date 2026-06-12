"""飞书交互机器人：发文字/语音 → Gemini 实时讲解（带上下文可追问）→ 回文字 + 语音。

部署形态（免费 7×24，与 Telegram 版同架构）：
- Render 免费 Web 服务跑本应用（render.yaml 一键蓝图），飞书事件订阅（webhook）收消息；
- Render 免费档闲置 15 分钟会休眠，由 cron-job.org 每 10 分钟 ping /healthz 保活；
- 飞书控制台配置与保活任务创建：python tools/setup_feishu.py（详见 ROADMAP.md）。

环境变量：FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_VERIFICATION_TOKEN（必填，开发者后台拿）、
GEMINI_API_KEY（必填）、WORK_PROFILE、ALLOWED_CHAT_IDS（逗号分隔的飞书 chat_id，
留空时机器人只回显 chat_id 供配置）、GEMINI_MODEL。

飞书侧约束（与 Telegram 不同处）：
- 事件订阅要求 3 秒内回 200，否则重投 3 次 → 收到立即 ack，后台处理，event_id 去重；
- 语音消息（voice 气泡）仅收发 opus：收到的直接喂 Gemini 多模态；回复的 mp3 用
  imageio-ffmpeg 自带的静态 ffmpeg 转 opus，转失败则只回文字。
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .config import load_config
from .tts import _synth_async

CFG = load_config()
APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
VERIFY_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
FS_API = "https://open.feishu.cn/open-apis"
# webhook 路径用 app_secret 哈希派生：本应用与 setup 脚本可独立算出，无需额外配置
SECRET = hashlib.sha256(f"timelyup:{APP_SECRET}".encode()).hexdigest()[:32]
ALLOWED = {x.strip() for x in os.environ.get("ALLOWED_CHAT_IDS", "").replace("，", ",").split(",") if x.strip()}

MAX_TURNS = 24        # 每个会话保留的对话条数（user+model 各算一条）
TEXT_LIMIT = 9000     # 飞书文本消息上限很大（150KB），仅作超长兜底分段

SYSTEM = f"""你是 timelyUP 对话助手，一名中文技术讲解人，正在和一位研发工程师进行多轮对话。

【听众工作背景】（结合它指出关联和可落地的应用；与背景无关的问题就客观讲解，不要硬扯）
{CFG.get('profile', '')}

要求：
- 回答口语化、有条理，内容会被直接转成语音朗读：不要出现任何 Markdown 符号、列表符号、网址、表情。
- 默认控制在 300~800 字；简单追问简短作答；用户明确要求展开时再加长。
- 客观准确，不确定的信息要说明是推测或传闻，不要编造数字和事实。
- 这是多轮对话，记住上下文，欢迎用户追问。"""

app = FastAPI()
_http = httpx.AsyncClient(timeout=60)
_history: dict[str, list] = {}      # chat_id -> [genai Content]
_voice_on: dict[str, bool] = {}     # chat_id -> 是否回语音（默认开）
_seen_events: dict[str, None] = {}  # 最近 event_id 去重（飞书超时会重投）
_token_cache: dict = {"token": "", "expires_at": 0.0}

HELP = (
    "你好，我是 timelyUP 对话助手。\n\n"
    "直接发文字或语音提问，我会结合你的工作背景讲解，回复文字加语音，支持连续追问。\n\n"
    "命令：\n/reset 清空当前对话上下文\n/voice 开/关语音回复\n/help 本说明"
)


def _gemini_call(contents: list) -> str:
    """同步调 Gemini（在线程里跑，避免阻塞事件循环）。"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=CFG["env"]["gemini_api_key"])
    resp = client.models.generate_content(
        model=CFG["env"]["gemini_model"],
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.6),
    )
    return (resp.text or "").strip()


async def _tenant_token() -> str:
    if time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    r = await _http.post(f"{FS_API}/auth/v3/tenant_access_token/internal",
                         json={"app_id": APP_ID, "app_secret": APP_SECRET})
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{data}")
    # 提前 5 分钟过期，避免边界上用到失效 token
    _token_cache.update(token=data["tenant_access_token"],
                        expires_at=time.time() + data.get("expire", 7200) - 300)
    return _token_cache["token"]


async def _send_text(chat_id: str, text: str) -> None:
    token = await _tenant_token()
    for i in range(0, len(text), TEXT_LIMIT):
        await _http.post(f"{FS_API}/im/v1/messages", params={"receive_id_type": "chat_id"},
                         headers={"Authorization": f"Bearer {token}"},
                         json={"receive_id": chat_id, "msg_type": "text",
                               "content": json.dumps({"text": text[i:i + TEXT_LIMIT]})})


def _mp3_to_opus(mp3: Path, opus: Path) -> int:
    """mp3 → ogg/opus（飞书语音气泡只认 opus）。返回时长毫秒（解析不到则 0）。"""
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [exe, "-y", "-i", str(mp3), "-c:a", "libopus", "-b:a", "32k", str(opus)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:  # 个别构建不带 libopus，退回 ffmpeg 自带 opus 编码器
        cmd = [exe, "-y", "-i", str(mp3), "-strict", "-2", "-c:a", "opus", "-b:a", "32k", str(opus)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码失败：{proc.stderr[-300:]}")
    m = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", proc.stderr)
    if not m:
        return 0
    h, mi, s, cs = (int(x) for x in m.groups())
    return ((h * 3600 + mi * 60 + s) * 100 + cs) * 10


async def _send_voice(chat_id: str, text: str) -> None:
    token = await _tenant_token()
    with tempfile.TemporaryDirectory() as td:
        mp3, opus = Path(td) / "answer.mp3", Path(td) / "answer.opus"
        await _synth_async(text, mp3, CFG.get("voice", {}))
        duration_ms = await asyncio.to_thread(_mp3_to_opus, mp3, opus)
        r = await _http.post(f"{FS_API}/im/v1/files",
                             headers={"Authorization": f"Bearer {token}"},
                             data={"file_type": "opus", "file_name": "answer.opus",
                                   "duration": str(duration_ms)},
                             files={"file": ("answer.opus", opus.read_bytes(), "audio/opus")})
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"上传语音失败：{data}")
    await _http.post(f"{FS_API}/im/v1/messages", params={"receive_id_type": "chat_id"},
                     headers={"Authorization": f"Bearer {token}"},
                     json={"receive_id": chat_id, "msg_type": "audio",
                           "content": json.dumps({"file_key": data["data"]["file_key"]})})


async def _download_resource(message_id: str, file_key: str) -> bytes:
    token = await _tenant_token()
    r = await _http.get(f"{FS_API}/im/v1/messages/{message_id}/resources/{file_key}",
                        params={"type": "file"}, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise RuntimeError(f"下载语音失败（{r.status_code}）：{r.text[:200]}")
    return r.content


async def _handle_message(event: dict) -> None:
    from google.genai import types

    msg = event.get("message", {})
    chat_id = msg.get("chat_id", "")
    msg_type = msg.get("message_type", "")
    try:
        content = json.loads(msg.get("content") or "{}")
    except ValueError:
        content = {}
    # 群里 @机器人 时文本带 @_user_N 占位符，去掉
    text = re.sub(r"@_user_\d+", "", content.get("text", "")).strip() if msg_type == "text" else ""

    # 未配置白名单时只回显 chat_id，配置后非白名单消息静默忽略（防陌生人烧 key）
    if not ALLOWED:
        await _send_text(chat_id, f"机器人尚未授权使用。本会话 chat_id 是 {chat_id}，"
                                  "请在 Render 环境变量 ALLOWED_CHAT_IDS 中填入它（保存后自动重启）。")
        return
    if chat_id not in ALLOWED:
        return

    if text.startswith("/start") or text.startswith("/help"):
        await _send_text(chat_id, HELP)
        return
    if text.startswith("/reset"):
        _history.pop(chat_id, None)
        await _send_text(chat_id, "已清空对话上下文，可以开新话题了。")
        return
    if text.startswith("/voice"):
        _voice_on[chat_id] = not _voice_on.get(chat_id, True)
        await _send_text(chat_id, "语音回复已" + ("开启" if _voice_on[chat_id] else "关闭（只回文字）"))
        return

    if msg_type not in ("text", "audio") or (msg_type == "text" and not text):
        await _send_text(chat_id, "请发文字或语音提问～")
        return

    history = _history.setdefault(chat_id, [])
    if msg_type == "audio":
        data = await _download_resource(msg["message_id"], content.get("file_key", ""))
        user_content = types.Content(role="user", parts=[
            types.Part(text="这是我的语音提问。请先用「你问的是：」开头一句话复述问题，然后回答。"),
            types.Part.from_bytes(data=data, mime_type="audio/ogg"),  # 飞书语音是 ogg/opus
        ])
        hist_text = "（语音提问，问题见你回答开头的复述）"
    else:
        user_content = types.Content(role="user", parts=[types.Part(text=text)])
        hist_text = text

    try:
        answer = await asyncio.to_thread(_gemini_call, history + [user_content])
    except Exception as e:  # noqa: BLE001
        await _send_text(chat_id, f"出错了：{e}\n稍后重试，或 /reset 后再问。")
        return
    if not answer:
        await _send_text(chat_id, "模型没有返回内容，请换个问法试试。")
        return

    # 语音原始字节不进历史，省内存也省后续请求的 token
    history.append(types.Content(role="user", parts=[types.Part(text=hist_text)]))
    history.append(types.Content(role="model", parts=[types.Part(text=answer)]))
    del history[:-MAX_TURNS]

    await _send_text(chat_id, answer)
    if _voice_on.get(chat_id, True):
        try:
            await _send_voice(chat_id, answer)
        except Exception as e:  # noqa: BLE001
            await _send_text(chat_id, f"（语音合成失败：{e}，本次仅文字回复）")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/fs/{secret}")
async def webhook(secret: str, request: Request) -> Response:
    if secret != SECRET:
        return Response(status_code=403)
    body = await request.json()

    # 配置事件订阅地址时飞书发的一次性校验
    if body.get("type") == "url_verification":
        if VERIFY_TOKEN and body.get("token") != VERIFY_TOKEN:
            return Response(status_code=403)
        return JSONResponse({"challenge": body.get("challenge", "")})

    header = body.get("header", {})
    if VERIFY_TOKEN and header.get("token") != VERIFY_TOKEN:
        return Response(status_code=403)

    eid = header.get("event_id", "")
    if eid in _seen_events:
        return Response(status_code=200)
    _seen_events[eid] = None
    while len(_seen_events) > 200:
        _seen_events.pop(next(iter(_seen_events)))

    if header.get("event_type") == "im.message.receive_v1":
        # 飞书要求 3 秒内回 200，否则重投；Gemini+TTS 几十秒，必须后台处理
        asyncio.create_task(_handle_message(body.get("event", {})))
    return Response(status_code=200)
