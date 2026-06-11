"""用 Gemini 精选资讯、撰写口播稿，并对每条做「研发应用分析」。

返回结构:
{
  "episode_title": "...",
  "intro": "...",
  "items": [
     {"title","source","link","summary","why_relevant","application"},
     ...
  ],
  "spoken_script": "完整中文口播稿（纯文本，供 TTS 朗读）"
}
"""
import json
import time

PROMPT_TEMPLATE = """你是一档面向研发工程师的中文科技早报主播兼技术分析师。
下面是今天从各信息源抓取到的候选资讯（JSON 数组）。

请完成：
1. 从中精选出最重要、最有信息量的 {max_items} 条，覆盖 AI 前沿、汽车智能化、机器人三个方向（按当天内容自然分布，不必强行凑数）。
2. 为每条写：一句话核心要点、为什么重要(why_relevant)、以及结合「我的工作背景」给出具体的应用分析(application)——能不能用、怎么用、值不值得投入。应用分析要务实、可操作，避免空话。
3. 写一篇自然流畅、适合**语音朗读**的中文口播稿(spoken_script)，目标时长约 {minutes} 分钟。要求：
   - 开头有简短问候和今日概览；中间逐条播报（要点 + 应用分析）；结尾一句话收束。
   - 口语化、有节奏，像电台主播。**不要**出现 Markdown 符号、网址、列表符号、表情。
   - 数字、英文术语用中文习惯读法（如 GPT 读作"GPT"，可保留英文缩写）。
4. 严格忠于候选资讯原文：产品名、型号、参数、数字只能来自原文，不得脑补或扩写；
   原文没提到的细节不要编造，不确定的信息要明确说明"据报道/尚未证实"。

【我的工作背景】
{profile}

【今日候选资讯】
{items_json}

只输出一个 JSON 对象，字段：episode_title, intro, items(数组，每项含 title, source, link, summary, why_relevant, application), spoken_script。不要输出任何额外文字。"""


def _fallback(items: list[dict], cfg: dict) -> dict:
    """没有 API key 或调用失败时，拼一个最简口播稿，保证流程跑通。"""
    picked = items[: cfg.get("ai", {}).get("max_items", 7)]
    lines = ["欢迎收听今天的科技研发早报。以下是今天精选的几条前沿进展。"]
    out_items = []
    for i, it in enumerate(picked, 1):
        lines.append(f"第{i}条，来自{it['source']}。{it['title']}。")
        if it["summary"]:
            lines.append(it["summary"][:200] + "。")
        out_items.append({**it, "why_relevant": "", "application": ""})
    lines.append("以上就是今天的内容，我们明天见。")
    return {
        "episode_title": "科技研发早报",
        "intro": lines[0],
        "items": out_items,
        "spoken_script": "\n".join(lines),
    }


def analyze(items: list[dict], cfg: dict) -> dict:
    env = cfg["env"]
    if not items:
        return {"episode_title": "科技研发早报", "intro": "", "items": [],
                "spoken_script": "今天没有抓取到符合条件的新内容，我们明天见。"}

    if not env["gemini_api_key"]:
        print("  [warn] 未设置 GEMINI_API_KEY，使用 fallback 口播稿")
        return _fallback(items, cfg)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=env["gemini_api_key"])
        prompt = PROMPT_TEMPLATE.format(
            max_items=cfg.get("ai", {}).get("max_items", 7),
            minutes=cfg.get("ai", {}).get("target_minutes", 7),
            profile=cfg.get("profile", "（未提供，按通用研发工程师处理）"),
            items_json=json.dumps(items, ensure_ascii=False),
        )
        cfg_obj = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
        )
        last_err = None
        for attempt in range(1, 4):  # 偶发网络/服务抖动，最多重试 3 次
            try:
                resp = client.models.generate_content(
                    model=env["gemini_model"],
                    contents=prompt,
                    config=cfg_obj,
                )
                data = json.loads(resp.text)
                if not data.get("spoken_script"):
                    raise ValueError("模型返回缺少 spoken_script")
                print(f"  AI 生成完成：《{data.get('episode_title','')}》，{len(data.get('items', []))} 条")
                return data
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"  [retry {attempt}/3] Gemini 调用失败：{e}")
                if attempt < 3:
                    time.sleep(3 * attempt)
        raise last_err
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] Gemini 多次调用失败({e})，使用 fallback")
        return _fallback(items, cfg)
