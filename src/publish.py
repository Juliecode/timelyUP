"""发布：维护节目清单(episodes.json)、生成播客 RSS(feed.xml) 与首页(index.html)。"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from feedgen.feed import FeedGenerator

from .config import DOCS, EPISODES_DIR


def _load_manifest() -> list[dict]:
    path = DOCS / "episodes.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _save_manifest(eps: list[dict]) -> None:
    (DOCS / "episodes.json").write_text(
        json.dumps(eps, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_show_notes(episode: dict) -> str:
    parts = []
    if episode.get("intro"):
        parts.append(episode["intro"])
    for i, it in enumerate(episode.get("items", []), 1):
        block = [f"{i}. {it.get('title', '')}（来源：{it.get('source', '')}）"]
        if it.get("application"):
            block.append(f"   应用分析：{it['application']}")
        if it.get("link"):
            block.append(f"   {it['link']}")
        parts.append("\n".join(block))
    return "\n\n".join(parts)


def publish(episode: dict, audio_path: Path, size_bytes: int, cfg: dict,
            slot: str = "am", slot_label: str = "晨报", date_str: str | None = None) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    base_url = cfg["env"]["base_url"]
    if not base_url:
        print("  [warn] 未设置 PAGES_BASE_URL，feed 中的音频链接将不可用（本地测试可忽略）")
        base_url = "https://example.invalid"

    now = datetime.now(timezone.utc)
    if date_str is None:
        date_str = (now + timedelta(hours=8)).strftime("%Y-%m-%d")
    ep_id = f"{date_str}-{slot}"  # 晨报/晚报各一集；同一时段重跑才覆盖
    base_title = episode.get("episode_title") or "科技研发早报"

    # 保存完整口播文稿（纯文本），供网页阅读 / 下载
    script_text = episode.get("spoken_script", "")
    transcript_name = audio_path.stem + ".txt"
    (EPISODES_DIR / transcript_name).write_text(script_text, encoding="utf-8")

    eps = _load_manifest()
    eps = [e for e in eps if e.get("id") != ep_id]
    eps.append({
        "id": ep_id,
        "date": date_str,
        "slot": slot,
        "title": f"{slot_label} · {base_title}",
        "notes": _build_show_notes(episode),
        "script": script_text,
        "file": audio_path.name,
        "transcript": transcript_name,
        "bytes": size_bytes,
        "pub": now.isoformat(),
    })
    eps.sort(key=lambda e: e.get("pub", ""), reverse=True)  # 按发布时间，最新在前

    # 清理超量旧集（含音频与文稿文件）
    keep = cfg.get("keep_episodes", 30)
    for old in eps[keep:]:
        for fname in (old.get("file"), old.get("transcript")):
            if fname and (EPISODES_DIR / fname).exists():
                (EPISODES_DIR / fname).unlink()
    eps = eps[:keep]
    _save_manifest(eps)

    _write_feed(eps, cfg, base_url)
    _write_index(eps, cfg, base_url)
    print(f"  已发布：{len(eps)} 集在线，feed.xml / index.html 已更新")


def _write_feed(eps: list[dict], cfg: dict, base_url: str) -> None:
    pod = cfg.get("podcast", {})
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title(pod.get("title", "TimelyUP"))
    fg.link(href=base_url, rel="alternate")
    fg.link(href=f"{base_url}/feed.xml", rel="self")  # atom:self 自引用
    fg.description(pod.get("description", ""))
    fg.language(pod.get("language", "zh-cn"))
    fg.author({"name": pod.get("author", "TimelyUP"), "email": pod.get("email", "")})
    fg.logo(f"{base_url}/cover.png")
    fg.podcast.itunes_author(pod.get("author", "TimelyUP"))
    fg.podcast.itunes_category(pod.get("category", "Technology"))
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_image(f"{base_url}/cover.png")

    for e in eps:
        fe = fg.add_entry()
        fe.id(f"{base_url}/episodes/{e['file']}")
        fe.title(e["title"])
        fe.description(e.get("notes", ""))
        fe.enclosure(f"{base_url}/episodes/{e['file']}", str(e.get("bytes", 0)), "audio/mpeg")
        fe.pubDate(datetime.fromisoformat(e["pub"]))

    # feedgen 只能输出 deprecated 的 <itunes:explicit>no</itunes:explicit>，
    # 现行规范要求 true/false，这里生成后替换，保证完全合规
    xml = fg.rss_str(pretty=True).decode("utf-8")
    xml = xml.replace("<itunes:explicit>no</itunes:explicit>",
                      "<itunes:explicit>false</itunes:explicit>")
    (DOCS / "feed.xml").write_text(xml, encoding="utf-8")


def _write_index(eps: list[dict], cfg: dict, base_url: str) -> None:
    pod = cfg.get("podcast", {})
    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")

    rows = []
    for e in eps:
        notes_html = esc(e.get("notes", ""))
        script_html = esc(e.get("script", ""))
        tx = e.get("transcript")
        tx_link = f' &nbsp;·&nbsp; <a href="{base_url}/episodes/{tx}" target="_blank">下载 .txt</a>' if tx else ""
        script_block = (
            f'<details><summary>完整口播文稿{tx_link}</summary><p>{script_html}</p></details>'
            if script_html else ""
        )
        rows.append(f"""
    <div class="ep">
      <h3>{e['title']}</h3>
      <div class="date">{e['date']}</div>
      <audio controls preload="none" src="{base_url}/episodes/{e['file']}"></audio>
      <details><summary>节目内容 / 应用分析</summary><p>{notes_html}</p></details>
      {script_block}
    </div>""")
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{pod.get('title', 'TimelyUP')}</title>
<style>
 body{{font-family:-apple-system,system-ui,sans-serif;max-width:760px;margin:0 auto;padding:20px;background:#0f1115;color:#e6e6e6}}
 h1{{font-size:1.4rem}} .sub{{color:#9aa0a6;margin-bottom:8px}}
 .feed{{background:#1b1f27;padding:10px 14px;border-radius:8px;word-break:break-all;font-size:.9rem}}
 .ep{{border-top:1px solid #2a2f3a;padding:16px 0}} .date{{color:#9aa0a6;font-size:.85rem;margin:4px 0}}
 audio{{width:100%;margin:8px 0}} a{{color:#7cb3ff}} details{{margin-top:6px}} summary{{cursor:pointer;color:#9aa0a6}}
</style></head><body>
<h1>{pod.get('title', 'TimelyUP')}</h1>
<div class="sub">{pod.get('description', '')}</div>
<p>在播客 App（Pocket Casts / Overcast 等）里订阅下面这个地址：</p>
<div class="feed">{base_url}/feed.xml</div>
{''.join(rows)}
</body></html>"""
    (DOCS / "index.html").write_text(html, encoding="utf-8")
