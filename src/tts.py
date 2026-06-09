"""文字转语音：用 edge-tts 把口播稿合成为 MP3，并生成带时间轴的 VTT 字幕。

VTT 字幕利用 edge-tts 的 WordBoundary 时间戳生成，可在支持 Podcasting 2.0
的 App（如 Pocket Casts）里随播放高亮显示。
"""
import asyncio
import re
from pathlib import Path

import edge_tts

# edge-tts 默认输出 24kHz/48kbps 单声道 MP3（恒定码率）→ 6000 字节/秒
_BYTES_PER_SEC = 48000 / 8


def _split(text: str, max_len: int = 1800) -> list[str]:
    """按段落/句子切块，单块不超过 max_len，避免单次请求过长。"""
    chunks: list[str] = []
    buf = ""
    for para in re.split(r"\n+", text.strip()):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 1 <= max_len:
            buf = f"{buf}\n{para}" if buf else para
        else:
            if buf:
                chunks.append(buf)
            if len(para) > max_len:
                sent = ""
                for piece in re.split(r"(?<=[。！？!?；;])", para):
                    if len(sent) + len(piece) <= max_len:
                        sent += piece
                    else:
                        if sent:
                            chunks.append(sent)
                        sent = piece
                if sent:
                    chunks.append(sent)
                buf = ""
            else:
                buf = para
    if buf:
        chunks.append(buf)
    return chunks


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _write_vtt(words: list[list], path: Path) -> bool:
    """把 (start, end, text) 词级时间戳合并成可读的字幕行，写成 WebVTT。"""
    if not words:
        return False
    lines: list[tuple] = []
    cur: list[str] = []
    cur_start = None
    cur_end = 0.0
    for s, e, t in words:
        if cur_start is None:
            cur_start = s
        cur.append(t)
        cur_end = e
        joined = "".join(cur)
        if len(joined) >= 18 or (t and t[-1] in "。！？!?，,；;："):
            lines.append((cur_start, cur_end, joined.strip()))
            cur, cur_start = [], None
    if cur:
        lines.append((cur_start, cur_end, "".join(cur).strip()))

    out = ["WEBVTT", ""]
    prev_end = 0.0
    n = 0
    for s, e, t in lines:
        if not t:
            continue
        if s < prev_end:   # 防止相邻字幕时间轴重叠
            s = prev_end
        if e <= s:
            e = s + 0.5
        n += 1
        out += [str(n), f"{_ts(s)} --> {_ts(e)}", t, ""]
        prev_end = e
    path.write_text("\n".join(out), encoding="utf-8")
    return True


async def _synth_async(text: str, out_path: Path, voice: dict) -> None:
    chunks = _split(text)
    words: list[list] = []
    cumulative = 0.0  # 之前所有块的音频累计时长（秒）
    with open(out_path, "wb") as f:
        for idx, chunk in enumerate(chunks, 1):
            communicate = edge_tts.Communicate(
                chunk,
                voice=voice.get("name", "zh-CN-YunyangNeural"),
                rate=voice.get("rate", "+0%"),
                volume=voice.get("volume", "+0%"),
            )
            chunk_bytes = 0
            async for part in communicate.stream():
                if part["type"] == "audio":
                    f.write(part["data"])
                    chunk_bytes += len(part["data"])
                elif part["type"] in ("WordBoundary", "SentenceBoundary"):
                    # 不同音色/参数下 edge-tts 可能给词级或句级时间戳，都兼容
                    start = cumulative + part["offset"] / 1e7
                    end = start + part["duration"] / 1e7
                    words.append([start, end, part.get("text", "")])
            cumulative += chunk_bytes / _BYTES_PER_SEC
            print(f"    配音进度 {idx}/{len(chunks)}")

    if _write_vtt(words, out_path.with_suffix(".vtt")):
        print("    字幕(VTT)已生成")


def synthesize(text: str, out_path: Path, cfg: dict) -> int:
    """合成 MP3（并在同名 .vtt 写入字幕），返回 MP3 字节数。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synth_async(text, out_path, cfg.get("voice", {})))
    size = out_path.stat().st_size
    print(f"  音频已生成：{out_path.name}（{size/1024:.0f} KB）")
    return size
