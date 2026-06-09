# TimelyUP · 科技研发早报（私人播客）

每天自动抓取 **AI / 汽车 / 机器人** 前沿资讯 → 用 AI 精选并分析「**能否用到你的研发工作**」→ 配音成中文口播 → 发布成一档**只属于你的播客**。iPhone 用播客 App 订阅即可，通勤/开车蓝牙直接听。

```
抓取 RSS  →  Gemini 精选+应用分析+口播稿  →  edge-tts 配音 MP3  →  更新播客 RSS  →  GitHub Pages
   src/fetch     src/analyze                    src/tts            src/publish        docs/
```

全程**免费**：GitHub Actions 每天定时跑，GitHub Pages 托管音频与 RSS，电脑无需开机。

---

## 一、本地先跑通（可选，5 分钟）

```powershell
# 1) 装依赖
pip install -r requirements.txt

# 2) 设置你的 Gemini key（本次终端会话有效）
$env:GEMINI_API_KEY = "你的_gemini_api_key"

# 3) 运行
python -m src.pipeline
```

生成的音频在 `docs/episodes/`，用浏览器打开 `docs/index.html` 即可试听。
> 不设 key 也能跑，但只会拼接摘要、没有 AI 应用分析（用于先验证链路）。

**先去改 `profile.md`** —— 把你真实的研发方向/技术栈/想解决的问题写进去，AI 的「应用分析」会准很多。

---

## 二、上线到 GitHub（每天自动推送）

1. **建仓库并推送**（在项目目录）：
   ```powershell
   git init
   git add .
   git commit -m "init timelyUP"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/timelyUP.git
   git push -u origin main
   ```

2. **加密钥**：仓库 → Settings → Secrets and variables → Actions → **New repository secret**
   - `GEMINI_API_KEY` = 你的 Gemini key
   - `WORK_PROFILE` = 你真实的工作背景（多行，直接粘贴；公开仓库下用它保密，不写进代码）

3. **加变量**：同页面切到 **Variables** 标签 → New variable
   - `PAGES_BASE_URL` = `https://<你的用户名>.github.io/timelyUP`
   - （可选）`GEMINI_MODEL` = `gemini-2.5-flash`

4. **开启 Pages**：Settings → Pages → Source 选 **Deploy from a branch** → 分支 `main`、目录 `/docs` → Save

5. **手动触发一次**：Actions 标签 → 左侧 “Daily Briefing” → **Run workflow**
   跑完后访问 `https://<你的用户名>.github.io/timelyUP/` 应能看到首页和今天这集。

之后每天**北京时间早 7:00（晨报）和晚 18:00（晚报）各更新一集**（改时间见 `.github/workflows/daily.yml` 的 cron）。晨报、晚报是两集独立节目，各自抓取当时最新资讯并单独做 AI 分析。

---

## 三、iPhone 订阅

把订阅地址 `https://<你的用户名>.github.io/timelyUP/feed.xml` 加进播客 App：

- **Pocket Casts**：右上 + → URL → 粘贴（推荐，体验最顺）
- **Overcast**：右上 + → Add URL
- Apple 自带「播客」App 加自定义 RSS 较绕，建议先用上面两个。

订阅后每天会自动下载当天那集，支持锁屏控制、倍速、车载蓝牙。

---

## 四、想改什么看这里

| 需求 | 改哪里 |
|------|--------|
| 抓哪些网站、关键词 | `config.yaml` 的 `sources` / `keywords` |
| 换声音、调语速 | `config.yaml` 的 `voice` |
| 每集几条、时长 | `config.yaml` 的 `ai.max_items` / `target_minutes` |
| 你的工作背景（影响应用分析） | `profile.md` |
| 推送时间/次数 | `.github/workflows/daily.yml` 的 `cron`（默认早7点+晚6点两集） |
| 换成 DeepSeek 等模型 | `src/analyze.py`（接口已隔离，替换 client 即可） |

## 目录结构
```
config.yaml          配置（源/声音/数量）
profile.md           你的工作背景
src/fetch.py         抓取 RSS
src/analyze.py       Gemini 精选 + 应用分析 + 口播稿
src/tts.py           edge-tts 配音
src/publish.py       生成播客 RSS + 首页
src/pipeline.py      主流程入口
docs/                GitHub Pages 根目录（feed.xml / index.html / episodes/*.mp3）
.github/workflows/   每日定时任务
```
