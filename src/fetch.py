"""抓取信息源：解析 RSS，按时间与关键词过滤，去重。"""
import re
import ssl
import urllib.request
from datetime import datetime, timezone, timedelta

import certifi
import feedparser

_TAG_RE = re.compile(r"<[^>]+>")
_UA = "timelyUP/1.0 (+https://github.com/; mailto:iiszhuying@gmail.com)"
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _parse_feed(url: str):
    """用 certifi 证书 + 自定义 UA 取原始内容再解析。
    解决部分平台 SSL 证书链问题、以及 arXiv 对 User-Agent 的要求。"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    raw = urllib.request.urlopen(req, context=_SSL_CTX, timeout=30).read()
    return feedparser.parse(raw)


def _clean(text: str, limit: int = 1000) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _entry_dt(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def fetch_items(cfg: dict) -> list[dict]:
    fetch_cfg = cfg.get("fetch", {})
    max_age = timedelta(hours=fetch_cfg.get("max_age_hours", 30))
    per_feed = fetch_cfg.get("per_feed_limit", 12)
    keywords = [k.lower() for k in cfg.get("keywords", [])]
    cutoff = datetime.now(timezone.utc) - max_age

    items: list[dict] = []
    seen_titles: set[str] = set()

    for src in cfg.get("sources", []):
        name = src.get("name", src.get("url", "?"))
        try:
            feed = _parse_feed(src["url"])
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 源解析失败 {name}: {e}")
            continue

        count = 0
        for entry in feed.entries:
            published = _entry_dt(entry)
            if published is not None and published < cutoff:
                continue

            title = _clean(entry.get("title", ""), 300)
            if not title:
                continue
            key = title.lower()
            if key in seen_titles:
                continue

            summary = _clean(entry.get("summary", "") or entry.get("description", ""), 1000)

            if not src.get("always", False) and keywords:
                blob = f"{title} {summary}".lower()
                if not any(k in blob for k in keywords):
                    continue

            seen_titles.add(key)
            items.append({
                "source": name,
                "title": title,
                "summary": summary,
                "link": entry.get("link", ""),
                "published": published.isoformat() if published else "",
            })
            count += 1
            if count >= per_feed:
                break
        print(f"  [{name}] 入选 {count} 条")

    print(f"候选池共 {len(items)} 条")
    return items
