"""主流程：抓取 → AI 分析 → 配音 → 发布。

本地测试：
    python -m src.pipeline
GitHub Actions 每天自动调用同一入口。
"""
import os
import sys
from datetime import datetime, timezone, timedelta

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文/emoji 报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

from .config import load_config, EPISODES_DIR
from .fetch import fetch_items
from .analyze import analyze
from .tts import synthesize
from .publish import publish, episode_exists


def main() -> None:
    print("=" * 50)
    print("TimelyUP 每日科技研发早报 —— 开始生成")
    print("=" * 50)

    cfg = load_config()

    # 北京时间 = UTC+8。据此判断晨报/晚报，并作为节目日期
    now_bj = datetime.now(timezone.utc) + timedelta(hours=8)
    slot = os.environ.get("FORCE_SLOT") or ("am" if now_bj.hour < 12 else "pm")
    slot_label = "晨报" if slot == "am" else "晚报"
    date_str = now_bj.strftime("%Y-%m-%d")

    # 兜底 cron 判重：定时触发时，若当天该时段已生成就跳过，避免重复出集、浪费 AI 调用。
    # 手动触发(workflow_dispatch)或本地运行不判重，方便强制重生成。
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and episode_exists(date_str, slot):
        print(f"\n[跳过] 今天的{slot_label}（{date_str}-{slot}）已生成，兜底 cron 无需重复。")
        return

    print("\n[1/4] 抓取信息源 ...")
    items = fetch_items(cfg)

    print("\n[2/4] AI 精选与应用分析 ...")
    episode = analyze(items, cfg)

    print(f"\n[3/4] 文字转语音 ...（{slot_label}）")
    audio_path = EPISODES_DIR / f"episode-{now_bj.strftime('%Y%m%d')}-{slot}.mp3"
    size = synthesize(episode["spoken_script"], audio_path, cfg)

    print("\n[4/4] 发布到播客 feed ...")
    publish(episode, audio_path, size, cfg,
            slot=slot, slot_label=slot_label, date_str=now_bj.strftime("%Y-%m-%d"))

    print("\n完成 ✅")


if __name__ == "__main__":
    main()
