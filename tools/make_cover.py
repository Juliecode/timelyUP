"""生成播客封面 docs/cover.png（1400x1400，符合播客规范）。

本地一次性运行即可：python tools/make_cover.py
（在 Windows 上用系统中文字体；生成的 PNG 提交进仓库，线上无需重跑）
"""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "cover.png"
SIZE = 1400

# 字体（Windows 中文字体）
def font(path_candidates, size):
    for p in path_candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

BOLD = ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"]
REG = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main():
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    top, bottom = (16, 20, 34), (24, 52, 96)  # 深蓝渐变
    for y in range(SIZE):
        c = lerp(top, bottom, y / SIZE)
        for x in range(SIZE):
            px[x, y] = c

    d = ImageDraw.Draw(img)

    # 顶部高亮圆点装饰
    accent = (90, 170, 255)
    d.ellipse([SIZE - 360, -160, SIZE + 160, 360], fill=(30, 70, 130))

    def centered(text, f, y, fill):
        bbox = d.textbbox((0, 0), text, font=f)
        w = bbox[2] - bbox[0]
        d.text(((SIZE - w) / 2, y), text, font=f, fill=fill)

    centered("TimelyUP", font(BOLD, 200), 430, (235, 242, 255))
    centered("科技研发早报", font(BOLD, 150), 680, (150, 195, 255))

    # 分隔线
    d.rectangle([SIZE / 2 - 280, 900, SIZE / 2 + 280, 908], fill=accent)

    centered("AI · 汽车 · 机器人", font(REG, 76), 960, (200, 212, 230))
    centered("每日前沿 · 研发视角", font(REG, 64), 1070, (150, 165, 190))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"封面已生成: {OUT}  ({OUT.stat().st_size/1024:.0f} KB, {SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
