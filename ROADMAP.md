# TimelyUP 开发进度与路线图

> 给未来的自己 / 协作者：当前状态、下一步要做什么，看这一份就够。

## ✅ 已完成（线上稳定运行）

- **每日播客**：GitHub Actions 定时（北京 07:00 晨报 / 18:00 晚报），抓取 AI/汽车/机器人/控制系统/电力电子等源 → Gemini 精选 + 结合 EPS 背景的应用分析 → edge-tts 配音 → 发布到 GitHub Pages 的私人播客 RSS。
- **按需专题**（`src/topic.py` + `.github/workflows/topic.yml`）：手机用 GitHub App 触发 On-demand Topic，填主题即生成一期讲解并入播客。
  - 支持**是否结合工作背景**开关：GitHub 勾选框 `use_profile` / 本地 `--no-profile`。
- **文字稿**：每集存 `.txt`（网页可读/下载）+ 带时间轴的 `.vtt` 字幕（feed 用 `podcast:transcript type="text/vtt"`，Pocket Casts 等可显示并高亮跟读）。
- **封面**：`docs/cover.png`（`tools/make_cover.py` 生成）。
- **背景保密**：仓库公开，真实 EPS 背景放在 `WORK_PROFILE` Secret（线上）/ `profile.local.md`（本地，已 gitignore）；`profile.md` 仅模板。

订阅地址：`https://juliecode.github.io/timelyUP/feed.xml` · 站点：`https://juliecode.github.io/timelyUP/`

## 🔜 下一步：交互式「对话追问」功能（待开发）

目标：**对手机说/打一个话题 → AI 实时讲解（文字+语音）→ 可在对话里继续追问**，带上下文、结合（可选）EPS 背景。

已定方向（2026-06）：
- **形态：Telegram 机器人**。发文字/语音消息 → Gemini（复用现有 key + profile）讲解 → 回文字 + edge-tts 语音 → 多轮对话天然带上下文。
- **托管：免费云主机**（Railway / Render / Fly 免费档，7×24，不依赖本地电脑）。
- 复用现有 `src/` 里的 Gemini 调用、profile 读取、edge-tts。

> 关键认知：现有「Actions 定时 + 静态 Pages」是**单向批量**，做不了交互。交互功能需要**常驻/serverless 后端**持有 key 并维持对话状态——这是新增的一层，不影响现有播客。

### 重启开发时的第一步
1. 选定并注册一个免费云主机 + 申请 Telegram BotFather token。
2. 在 `src/` 下新建 bot 服务（webhook 或 long-polling），接消息 → 调 Gemini → 回复（文字/语音）。
3. 复用 `config.load_config()` 的 profile 与 key 读取；语音用 `tts.synthesize` 或直接 edge-tts。

## 配置速查
- 内容源/音色/数量/时长：`config.yaml`
- 工作背景：`WORK_PROFILE` Secret（线上）/ `profile.local.md`（本地）
- 推送时间：`.github/workflows/daily.yml` 的 cron（UTC，北京=UTC+8）
- 模型：`GEMINI_MODEL` 变量（默认 gemini-2.5-flash）；**Key 必须是 `AIzaSy` 开头的持久 key，不能用 `AQ.` 开头的临时令牌（会过期）**
