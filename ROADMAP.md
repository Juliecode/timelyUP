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

## 🚧 交互式「对话追问」功能（飞书版代码已完成，待部署）

目标：**对手机说/打一个话题 → AI 实时讲解（文字+语音）→ 可在对话里继续追问**，带上下文、结合 EPS 背景。

载体决策（2026-06-13）：**飞书机器人**。原 Telegram 版（`src/bot.py` + `tools/setup_telegram.py`）代码保留但弃用——Telegram 对 +86 新注册基本不发短信验证码（运营商收费过高），国内注册门槛太高；飞书国区直装、零代理、API 对个人开发者友好。微信个人号无官方 API（封号风险）、公众号被动回复限 5 秒（来不及跑 Gemini），均不可行。

已实现：
- **`src/feishu_bot.py`**：飞书事件订阅机器人（FastAPI）。文字/语音提问（语音 opus 直接喂 Gemini 多模态转写+回答）→ 回文字 + edge-tts 语音（mp3 经 imageio-ffmpeg 转 opus 发语音气泡）；多轮上下文（每会话留 24 条，`/reset` 清空）；`/voice` 开关语音回复；`ALLOWED_CHAT_IDS` 白名单防陌生人烧 key（留空时只回显 chat_id 供配置）；事件 3 秒内 ack、event_id 去重。
- **`render.yaml`**：Render 免费 Web 服务一键蓝图（`requirements-bot.txt` 装依赖），指向 feishu_bot。
- **`tools/setup_feishu.py`**：校验飞书凭据 + 打印事件订阅地址（手动贴进开发者后台）+ 在 cron-job.org 建每 10 分钟保活任务（防 Render 免费档休眠，实现免费 7×24）。

### 部署步骤（一次性，约 15 分钟）
1. 手机装飞书 App 注册（国内手机号即可）→ 网页登录 [open.feishu.cn](https://open.feishu.cn) 开发者后台 → 创建**企业自建应用**，记下 App ID / App Secret / Verification Token（凭证与基础信息、事件与回调页）。
2. 应用里**添加机器人能力**；权限管理开通：`im:message`、`im:message:send_as_bot`、`im:resource`。
3. render.com 用 GitHub 登录 → New → Blueprint → 选本仓库 → 填 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_VERIFICATION_TOKEN / GEMINI_API_KEY / WORK_PROFILE → 部署，记下服务地址。
4. 把 App ID / Secret / 服务地址填进 `.secrets.local.json`（feishu_app_id / feishu_app_secret / bot_url），跑 `python tools/setup_feishu.py`——它会校验凭据、建保活任务，并打印**事件订阅请求地址**。
5. 开发者后台 → 事件与回调：订阅方式选「将事件发送至开发者服务器」，贴入上一步地址（Encrypt Key 留空）；添加事件 `im.message.receive_v1`（接收消息）。
6. 版本管理与发布 → 创建版本 → 申请发布（自己是管理员，秒过）。
7. 飞书里搜机器人名字发条消息 → 它回 chat_id → 填进 Render 环境变量 ALLOWED_CHAT_IDS → 完成。

> 关键认知：现有「Actions 定时 + 静态 Pages」是**单向批量**，做不了交互。交互功能是**常驻后端**这一新增层，不影响现有播客。

## 配置速查
- 内容源/音色/数量/时长：`config.yaml`
- 工作背景：`WORK_PROFILE` Secret（线上）/ `profile.local.md`（本地）
- 推送时间：`.github/workflows/daily.yml` 的 cron（UTC，北京=UTC+8）
- 模型：`GEMINI_MODEL` 变量（默认 gemini-2.5-flash）；**Key 必须是 `AIzaSy` 开头的持久 key，不能用 `AQ.` 开头的临时令牌（会过期）**
