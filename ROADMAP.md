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

## 🚧 交互式「对话追问」功能（代码已完成，待部署）

目标：**对手机说/打一个话题 → AI 实时讲解（文字+语音）→ 可在对话里继续追问**，带上下文、结合 EPS 背景。

已实现（2026-06-11）：
- **`src/bot.py`**：Telegram webhook 机器人（FastAPI）。文字/语音提问（语音直接喂 Gemini 多模态转写+回答）→ 回文字 + edge-tts 语音；多轮上下文（每会话留 24 条，`/reset` 清空）；`/voice` 开关语音回复；`ALLOWED_CHAT_IDS` 白名单防陌生人烧 key（留空时只回显 chat_id 供配置）。
- **`render.yaml`**：Render 免费 Web 服务一键蓝图（`requirements-bot.txt` 装依赖）。
- **`tools/setup_telegram.py`**：一键注册 webhook + 在 cron-job.org 建每 10 分钟保活任务（防 Render 免费档休眠，实现免费 7×24）。

### 部署步骤（一次性，约 10 分钟）
1. Telegram 里找 @BotFather `/newbot` 拿 token。
2. render.com 用 GitHub 登录 → New → Blueprint → 选本仓库 → 填 TELEGRAM_BOT_TOKEN / GEMINI_API_KEY / WORK_PROFILE → 部署，记下服务地址。
3. 把 token、服务地址填进 `.secrets.local.json`（telegram_bot_token / bot_url），跑 `python tools/setup_telegram.py`。
4. 给机器人发条消息 → 它回 chat_id → 填进 Render 环境变量 ALLOWED_CHAT_IDS → 完成。

> 关键认知：现有「Actions 定时 + 静态 Pages」是**单向批量**，做不了交互。交互功能是**常驻后端**这一新增层，不影响现有播客。

## 配置速查
- 内容源/音色/数量/时长：`config.yaml`
- 工作背景：`WORK_PROFILE` Secret（线上）/ `profile.local.md`（本地）
- 推送时间：`.github/workflows/daily.yml` 的 cron（UTC，北京=UTC+8）
- 模型：`GEMINI_MODEL` 变量（默认 gemini-2.5-flash）；**Key 必须是 `AIzaSy` 开头的持久 key，不能用 `AQ.` 开头的临时令牌（会过期）**
