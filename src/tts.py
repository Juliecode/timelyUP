"""文字转语音：用 edge-tts 把口播稿合成为 MP3。"""
import asyncio
import re
from pathlib import Path

import edge_tts


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
            # 段落本身过长则再按句号切
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


async def _synth_async(text: str, out_path: Path, voice: dict) -> None:
    chunks = _split(text)
    with open(out_path, "wb") as f:
        for idx, chunk in enumerate(chunks, 1):
            communicate = edge_tts.Communicate(
                chunk,
                voice=voice.get("name", "zh-CN-YunyangNeural"),
                rate=voice.get("rate", "+0%"),
                volume=voice.get("volume", "+0%"),
            )
            async for part in communicate.stream():
                if part["type"] == "audio":
                    f.write(part["data"])
            print(f"    配音进度 {idx}/{len(chunks)}")


def synthesize(text: str, out_path: Path, cfg: dict) -> int:
    """合成并返回文件字节数。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synth_async(text, out_path, cfg.get("voice", {})))
    size = out_path.stat().st_size
    print(f"  音频已生成：{out_path.name}（{size/1024:.0f} KB）")
    return size
