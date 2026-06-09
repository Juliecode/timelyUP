"""按指定主题实时生成一期「专题」讲解（文字 + 语音），并加入播客 feed。

本地用法:
    python -m src.topic "SiC 在 EPS 逆变器中的应用"
GitHub Actions 手动触发时通过环境变量 TOPIC 传入（见 .github/workflows/topic.yml）。
"""
import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta

# Windows 控制台强制 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

from .config import load_config, EPISODES_DIR
from .tts import synthesize
from .publish import publish

PROMPT = """你是面向研发工程师的中文技术讲解人。请就下面这个主题，做一期适合**语音收听**的讲解。

【主题】
{topic}

【听众的工作背景】（请结合它，指出与听众工作的关联和可落地的应用）
{profile}

要求：
1. 口语化、有条理，像电台科普，目标时长约 {minutes} 分钟。不要出现 Markdown 符号、网址、列表符号、表情。
2. 结构建议：开场点题 → 它是什么/核心原理 → 为什么重要/现状 → 与听众工作的结合点和可落地的应用 → 一句话小结。
3. 客观准确；不确定处说明是趋势或推测，不要编造具体数字或事实。

只输出一个 JSON 对象，字段：episode_title(简洁标题), spoken_script(完整讲解口播稿，纯文本), key_points(3-6 条要点的字符串数组)。不要输出任何额外文字。"""


def generate(topic: str, cfg: dict) -> dict:
    env = cfg["env"]
    if not env["gemini_api_key"]:
        raise SystemExit("未设置 GEMINI_API_KEY，无法生成专题。请配置后重试。")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=env["gemini_api_key"])
    prompt = PROMPT.format(
        topic=topic,
        profile=cfg.get("profile") or "（通用研发工程师）",
        minutes=cfg.get("ai", {}).get("target_minutes", 7),
    )
    cfg_obj = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7)
    last = None
    for attempt in range(1, 4):
        try:
            resp = client.models.generate_content(model=env["gemini_model"], contents=prompt, config=cfg_obj)
            data = json.loads(resp.text)
            if not data.get("spoken_script"):
                raise ValueError("模型返回缺少 spoken_script")
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  [retry {attempt}/3] Gemini 调用失败：{e}")
            if attempt < 3:
                time.sleep(3 * attempt)
    raise last


def main() -> None:
    topic = " ".join(sys.argv[1:]).strip() or os.environ.get("TOPIC", "").strip()
    if not topic:
        raise SystemExit('用法: python -m src.topic "你的话题"')

    cfg = load_config()
    print(f"🎯 生成专题：{topic}\n")

    data = generate(topic, cfg)
    points = data.get("key_points", []) or []
    episode = {
        "episode_title": data.get("episode_title") or topic,
        "intro": f"本期专题：{topic}",
        "items": [{"title": p, "source": "专题讲解", "link": "", "application": ""} for p in points],
        "spoken_script": data["spoken_script"],
    }
    print(f"  AI 生成完成：《{episode['episode_title']}》")

    now_bj = datetime.now(timezone.utc) + timedelta(hours=8)
    stamp = now_bj.strftime("%H%M%S")
    audio_path = EPISODES_DIR / f"episode-{now_bj.strftime('%Y%m%d')}-topic-{stamp}.mp3"

    print("  配音中 ...")
    size = synthesize(episode["spoken_script"], audio_path, cfg)

    publish(episode, audio_path, size, cfg,
            slot=f"topic-{stamp}", slot_label="专题", date_str=now_bj.strftime("%Y-%m-%d"))
    print("\n完成 ✅ 已作为一期「专题」加入播客，订阅的 App 刷新即可收听。")


if __name__ == "__main__":
    main()
