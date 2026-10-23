# token-receipt

把某一天的 AI 编程用量打成一张小票：Claude Code、Codex、WorkBuddy 按模型列出 token、缓存读写、按 API 标价折算的金额，以及订阅额度用满的次数。输出是一个自包含的静态 HTML（任何人打开即看），并可截成 PNG。

A receipt for a day of AI coding usage: tokens by model (Claude Code, Codex, WorkBuddy), cache reads and writes, API-list-price estimates, and plan-limit hits. Outputs a self-contained static HTML page and a PNG screenshot. Chinese and English, six scenes.

## 特点

- **只读本机**：读取 `~/.claude/projects`、`~/.codex/sessions`、`~/.workbuddy/projects` 下的会话记录，只取 token 数、模型名、时间和额度信息，不保存提问与回答。
- **不联网出数据**：数据全部来自本机日志。只有 `--price` 与 `--check-prices` 会访问 OpenRouter 的公开价目表。
- **只用标准库**：一个 Python 3 文件，无需安装依赖。
- **六种场景**：热敏打印机（纸从出纸口吐出）、木桌、软木板、手账（胶带）、账单夹板、纯净。底纹与动画全部是 CSS，不含图片文件。
- **中英文**：`--lang zh|en|all`。

## 安装

需要 Python 3.10+。PNG 需要本机 Chrome 或 Chromium（没有时只出 HTML）。

```bash
git clone https://github.com/2562771185/token-receipt.git
```

作为 Claude Code skill 使用：把整个目录放进 `~/.claude/skills/token-receipt/`，Claude Code 会读取 `SKILL.md`，用户说「token 小票」之类时自动触发。

## 用法

```bash
# 今天的小票（中文，打印机场景），输出到 ~/Downloads
python3 receipt.py

# 指定日期，中英文 × 六种场景，共 12 份
python3 receipt.py --date 2026-10-22 --lang all --scene all

# 只出 HTML，输出到指定目录
python3 receipt.py --no-png --out ./out

# 查询模型实际价格（OpenRouter 与本地表对照）
python3 receipt.py --price claude-opus-5-5 gpt-5.5

# 校对本地价目表与 OpenRouter
python3 receipt.py --check-prices
```

主要参数：

| 参数 | 说明 |
| --- | --- |
| `--date YYYY-MM-DD` | 日期，缺省今天（本机时区） |
| `--lang zh\|en\|all` | 语言，缺省 `zh` |
| `--scene printer\|desk\|cork\|tape\|clip\|plain\|all` | 场景，缺省 `printer` |
| `--out DIR` | 输出目录，缺省 `~/Downloads` |
| `--host` | 在小票上印本机局域网 IP 与系统版本（分享前注意） |
| `--no-png` | 只出 HTML |
| `--height PX` | PNG 视窗高度，缺省 1300，小票被截断时调大 |
| `--price MODEL...` | 查询模型价格，不出小票 |
| `--check-prices` | 列出本地价目表与 OpenRouter 不一致的项 |

环境变量 `TOKEN_RECEIPT_CHROME` 可指定截图用的浏览器路径。

## 金额怎么算

金额是按 API 标价估算的，**订阅用户并不实际支付这些钱**。

- 价格表是脚本里的 `PRICES`（美元 / 百万 token）。缓存写 5 分钟为输入价的 1.25 倍，1 小时为 2 倍，快速模式按表内倍数计。
- OpenRouter 价目表缓存在 `~/.cache/token-receipt/openrouter-models.json`，一天刷新一次。删掉该文件即强制重新拉取。
- 不在价格表里的模型只列 token，不计金额，小票上会标「—」。
- WorkBuddy 没有公开单价，只列 token。

## 数字的边界

- 只统计本机日志里有的用量。claude.ai 网页版与 Claude 桌面版聊天的用量不在本机日志中，但共用同一份订阅额度。
- Claude 的日志只记录「额度用满」的次数与重置时间，不记录用了百分之几。
- 同一台电脑上用过多个账号时，它们的会话会合并统计。

## 开发

```bash
ruff check receipt.py
python3 receipt.py --lang all --scene all --out /tmp/receipt-test
```

价格表与插件 [Token 小票](https://github.com/MatsuriMW/token-receipt) 的 `DEFAULT_PRICES` 保持一致；解析规则也参照该插件。

## 许可

[MIT](LICENSE)
