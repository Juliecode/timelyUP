"""Telegram 交互机器人：发文字/语音 → Gemini 实时讲解（带上下文可追问）→ 回文字 + 语音。

部署形态（免费 7×24）：
- Render 免费 Web 服务跑本应用（render.yaml 一键蓝图），webhook 模式收消息；
- Render 免费档闲置 15 分钟会休眠，由 cron-job.org 每 10 分钟 ping /healthz 保活；
- webhook 注册与保活任务创建：python tools/setup_telegram.py（详见 ROADMAP.md）。

环境变量：TELEGRAM_BOT_TOKEN（必填）、GEMINI_API_KEY（必填）、WORK_PROFILE、
ALLOWED_CHAT_IDS（逗号分隔，留空时机器人只回显 chat_id 供配置）、GEMINI_MODEL。
"""
import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response

from .config import load_config
from .tts import _synth_async

CFG = load_config()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_API = f"https://api.telegram.org/bot{TOKEN}"
# webhook 路径与 Telegram secret_token 都用 token 的哈希派生：双方可独立算出，无需额外配置
SECRET = hashlib.sha256(f"timelyup:{TOKEN}".encode()).hexdigest()[:32]
ALLOWED = {int(x) for x in os.environ.get("ALLOWED_CHAT_IDS", "").replace("，", ",").split(",") if x.strip().lstrip("-").isdigit()}

MAX_TURNS = 24          # 每个会话保留的对话条数（user+model 各算一条）
TG_TEXT_LIMIT = 3900    # Telegram 单条消息上限 4096，留余量

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
_history: dict[int, list] = {}      # chat_id -> [genai Content]
_voice_on: dict[int, bool] = {}     # chat_id -> 是否回语音（默认开）
_seen_updates: dict[int, None] = {}  # 最近 update_id 去重（Telegram 超时会重投）

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


async def _send_text(chat_id: int, text: str) -> None:
    for i in range(0, len(text), TG_TEXT_LIMIT):
        await _http.post(f"{TG_API}/sendMessage",
                         json={"chat_id": chat_id, "text": text[i:i + TG_TEXT_LIMIT]})


async def _send_voice(chat_id: int, text: str) -> None:
    await _http.post(f"{TG_API}/sendChatAction", json={"chat_id": chat_id, "action": "record_voice"})
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "answer.mp3"
        await _synth_async(text, mp3, CFG.get("voice", {}))
        await _http.post(f"{TG_API}/sendAudio",
                         data={"chat_id": str(chat_id), "title": "语音讲解"},
                         files={"audio": ("answer.mp3", mp3.read_bytes(), "audio/mpeg")})


async def _download_tg_file(file_id: str) -> bytes:
    r = await _http.get(f"{TG_API}/getFile", params={"file_id": file_id})
    path = r.json()["result"]["file_path"]
    r = await _http.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}")
    return r.content


async def _handle_message(msg: dict) -> None:
    from google.genai import types

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()

    # 未配置白名单时只回显 chat_id，配置后非白名单消息静默忽略（防陌生人烧 key）
    if not ALLOWED:
        await _send_text(chat_id, f"机器人尚未授权使用。你的 chat_id 是 {chat_id}，"
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

    voice = msg.get("voice") or msg.get("audio")
    if not text and not voice:
        await _send_text(chat_id, "请发文字或语音提问～")
        return

    await _http.post(f"{TG_API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})

    history = _history.setdefault(chat_id, [])
    if voice:
        data = await _download_tg_file(voice["file_id"])
        user_content = types.Content(role="user", parts=[
            types.Part(text="这是我的语音提问。请先用「你问的是：」开头一句话复述问题，然后回答。"),
            types.Part.from_bytes(data=data, mime_type=voice.get("mime_type") or "audio/ogg"),
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


@app.post("/tg/{secret}")
async def webhook(secret: str, request: Request) -> Response:
    if secret != SECRET or request.headers.get("x-telegram-bot-api-secret-token") != SECRET:
        return Response(status_code=403)
    update = await request.json()
    uid = update.get("update_id")
    if uid in _seen_updates:
        return Response(status_code=200)
    _seen_updates[uid] = None
    while len(_seen_updates) > 200:
        _seen_updates.pop(next(iter(_seen_updates)))
    msg = update.get("message")
    if msg:
        # 立即回 200，后台处理；否则 Gemini+TTS 几十秒会让 Telegram 超时重投
        asyncio.create_task(_handle_message(msg))
    return Response(status_code=200)
