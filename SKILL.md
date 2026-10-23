---
name: token-receipt
description: 把某一天 Claude Code / Codex / WorkBuddy 的 token 用量打成一张小票，输出静态 HTML（任何人打开即看，带场景底纹和入场动画）和 PNG 图片，支持中文与英文。用户说「token 小票」「用量小票」「打印用量」「今天用了多少 token」「出一张小票」「AI 用量结算单」时触发。
---

在本机运行 `receipt.py`：只读会话记录，不联网出数据（只在 `--price` 与 `--check-prices` 时访问 OpenRouter 价目表），只用标准库。每个版本输出一个自包含的 HTML，并用本机 Chrome 无头模式截一张 PNG（截图为落定后的静态画面）。

**执行步骤：**

1. 默认出今天的小票（中文、打印机场景）。`receipt.py` 放在哪个目录就用哪个路径：

   ```
   python3 <skill 目录>/receipt.py
   ```

   用户要"每个版本都要一份"时，加 `--lang all --scene all`，一次出 12 份（中英 × 六种场景）。
2. 脚本会逐个打印 HTML 与 PNG 的绝对路径。把这些路径都告诉用户。
3. 缺省输出到 `~/Downloads/`，文件名为 `token-receipt-YYYY-MM-DD-<场景>-<语言>.html`（同名 `.png`）。

**参数：**

- `--date YYYY-MM-DD`：指定日期，缺省今天。
- `--lang zh|en|all`：语言，缺省 `zh`；`all` 出中英两份。
- `--scene printer|desk|cork|tape|clip|plain|all`：场景，缺省 `printer`（热敏打印机，纸从出纸口吐出并迸彩纸）；`all` 出六种。
  - `printer` 打印机出纸；`desk` 木桌；`cork` 软木板（红图钉）；`tape` 手账纸（胶带）；`clip` 账单夹板；`plain` 纯净背景（淡入）。
- `--out <目录>`：输出目录，缺省 `~/Downloads`。
- `--host`：在小票上印本机局域网 IP 和系统版本。缺省不印，因为 HTML 通常会被分享；用户明确要求时才加。
- `--no-png`：只出 HTML，不截图。
- `--price <模型名> ...`：查询模型实际价格，只打印不出小票。数据来自 OpenRouter 公开价目表（无需密钥），并与本地表对照；例如 `--price claude-opus-5-5 gpt-5.5`。
- `--check-prices`：把本地 `PRICES` 与 OpenRouter 逐项校对，列出不一致的项。
- OpenRouter 价目表缓存在 `~/.cache/token-receipt/openrouter-models.json`，一天刷新一次；删掉该文件即强制重新拉取。联网失败时只显示本地表。
- `--height <像素>`：PNG 视窗高度，缺省 1300。小票被截断时调大。

**数据口径（与 Obsidian 插件 Token 小票一致）：**

- Claude Code：`~/.claude/projects` 下每条 assistant 消息的 `message.usage`，按 `message.id|requestId` 去重；额度用满的提示与重置时间。
- Codex：`~/.codex/sessions` 与 `archived_sessions` 下 `token_count` 的累计值逐条相减；最后一条的周额度占用。
- WorkBuddy：`~/.workbuddy/projects` 下 `providerData.rawUsage`，只列 token 不计价。
- 金额按 `receipt.py` 内 `PRICES`（美元 / 百万 token）折算，是 API 标价估算，订阅用户并非实付。价目表变动时，与插件的 `DEFAULT_PRICES` 一起改。

**不包含：** Magpie 数据；插件的动画 SVG 导出（这里的动画是 HTML 内的 CSS 动画）。
