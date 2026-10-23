#!/usr/bin/env python3
"""把某一天 Claude Code / Codex / WorkBuddy 的 token 用量打成一张小票（静态 HTML，并截一张 PNG）。

只读本机会话记录，不联网，只用标准库。解析规则与 Obsidian 插件 Token 小票（MatsuriMW/token-receipt）一致。
用法：python3 receipt.py [--date YYYY-MM-DD] [--lang zh|en] [--scene printer|desk|cork|tape|clip|plain|all] [--out 路径] [--host]
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import platform
import random
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

M = 1e6
# 美元 / 百万 token；read 为缓存读，缺省按输入价一成；缓存写 5m 为输入价 1.25 倍、1h 为 2 倍；fast 为快速模式倍数
# 与插件 DEFAULT_PRICES 同步，价格变动时两边一起改
PRICES = {
    "claude-fable-5-1": {"in": 10, "out": 50, "read": 0.25},
    "claude-fable-5": {"in": 10, "out": 50, "read": 1},
    "claude-opus-5-5": {"in": 4, "out": 20, "read": 0.2, "fast": 2},
    "claude-opus-5": {"in": 5, "out": 25, "read": 0.5, "fast": 2},
    "claude-opus-4-8": {"in": 5, "out": 25, "read": 0.5},
    "claude-opus-4-7": {"in": 5, "out": 25, "read": 0.5},
    "claude-opus-4-6": {"in": 5, "out": 25, "read": 0.5},
    "claude-sonnet-5-5": {"in": 2, "out": 10, "read": 0.1},
    "claude-sonnet-5": {"in": 2, "out": 10, "read": 0.2},
    "claude-sonnet-4-6": {"in": 3, "out": 15, "read": 0.3},
    "claude-haiku-5-5": {"in": 0.1, "out": 0.5, "read": 0.01},
    "claude-haiku-4-5": {"in": 1, "out": 5, "read": 0.1},
    "gpt-5.5": {"in": 5, "out": 30, "read": 0.5},
    "gpt-5.4": {"in": 2.5, "out": 15, "read": 0.25},
    "gpt-5.4-mini": {"in": 0.75, "out": 4.5, "read": 0.075},
    "gpt-5.3-codex": {"in": 1.75, "out": 14},
    "gpt-5.2-codex": {"in": 1.75, "out": 14, "read": 0.175},
    "gpt-5.1-codex-mini": {"in": 0.25, "out": 2, "read": 0.03},
    "gpt-5.6-terra": {"in": 2, "out": 12, "read": 0.2},
    "gpt-5.6-sol": {"in": 4, "out": 20, "read": 0.4},
    "gpt-6-luna": {"in": 0.1, "out": 0.5, "read": 0.01},
    "gpt-6.1-sol": {"in": 2, "out": 10, "read": 0.1},
    "gpt-6-astra": {"in": 10, "out": 50, "read": 1},
    "deepseek/deepseek-v4-pro": {"in": 0.95526, "out": 1.91052, "read": 0.079605},
}
# 2026-10-23 查询：Anthropic 与上表对照官方价目页一致；OpenAI、DeepSeek 取自 OpenRouter 价目表（与官方价或有出入）。
# 未建模：OpenAI 超过 272k 输入的长上下文档位、Haiku 5.5 超过 100k 的档位。

SOURCES = {
    "claude": "~/.claude/projects",
    "codex": "~/.codex/sessions",
    "wb": "~/.workbuddy/projects",
}
CODEX_ARCHIVE = "~/.codex/archived_sessions"
LINE_ORDER = {
    "claude": ["input", "output", "read", "write5", "write1h"],
    "codex": ["input", "read", "output"],
    "wb": ["input", "hit", "output"],
}
SCENES = ("printer", "desk", "cork", "tape", "clip", "plain")

I18N = {
    "zh": {
        "lang": "zh-CN", "title": "TOKEN 小票", "subtitle": "AI 用量结算单", "no": "单号", "printed": "出票",
        "item": "品名", "amount": "金额 USD", "sessions": "{n} 个会话 · {m} 次请求", "times": "× {n} 次",
        "subtotal": "小计", "not_priced": "不计价", "unpriced_mark": "—",
        "input": "输入", "output": "输出", "read": "缓存读", "write5": "缓存写 5m", "write1h": "缓存写 1h", "hit": "缓存命中",
        "limit": {"five_hour": "5 小时额度用满", "seven_day": "周额度用满", "other": "额度用满"},
        "quota": {"five_hour": "5 小时额度已用", "seven_day": "周额度已用", "other": "额度已用"},
        "resets": "重置", "total": "合计 TOKEN", "api": "API 折算",
        "note": "金额按 API 标价折算，订阅用户并非实付",
        "unpriced_note": "标「—」的模型不在价目表里，未计入金额",
        "none": "今日无消费", "table": "桌号", "seat": "餐位", "thanks": "谢谢惠顾 · THANK YOU",
        "weekday": ["一", "二", "三", "四", "五", "六", "日"], "date": "{d} 星期{w}",
    },
    "en": {
        "lang": "en", "title": "TOKEN RECEIPT", "subtitle": "AI usage statement", "no": "No.", "printed": "Printed",
        "item": "Item", "amount": "Amount USD", "sessions": "{n} sessions · {m} requests", "times": "× {n}",
        "subtotal": "Subtotal", "not_priced": "not priced", "unpriced_mark": "—",
        "input": "Input", "output": "Output", "read": "Cache read", "write5": "Cache write 5m", "write1h": "Cache write 1h",
        "hit": "Cache hit",
        "limit": {"five_hour": "5-hour limit hit", "seven_day": "Weekly limit hit", "other": "Limit hit"},
        "quota": {"five_hour": "5-hour limit used", "seven_day": "Weekly limit used", "other": "Limit used"},
        "resets": "Resets", "total": "TOTAL TOKEN", "api": "API equivalent",
        "note": "Amounts are API list prices; subscribers don't pay them",
        "unpriced_note": "Models marked — are not in the price table and aren't counted",
        "none": "No usage today", "table": "Table", "seat": "Seat", "thanks": "THANK YOU",
        "weekday": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "date": "{w} {d}",
    },
}
SECTION_NAMES = {"claude": "CLAUDE CODE", "codex": "CODEX", "wb": "WORKBUDDY"}


def expand(p):
    return Path(p).expanduser()


def ts(v):
    """时间转成 Unix 秒；数字按毫秒处理（WorkBuddy 的写法）。"""
    if isinstance(v, (int, float)):
        return v / 1000
    if isinstance(v, str) and v:
        try:
            return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def loads(line):
    try:
        d = json.loads(line)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        yield from f


def price_of(model):
    m = re.sub(r"^(claude-[a-z]+-\d+)\.(\d+)$", r"\1-\2", model)  # claude-sonnet-5.5 与 claude-sonnet-5-5 是同一个模型
    if m in PRICES:
        return PRICES[m]
    base = re.sub(r"-(\d{8}|\d{4}-\d{2}-\d{2})$", "", m)
    return PRICES.get(base)


def model_label(mid):
    if not mid.startswith("claude-"):
        return mid
    parts = re.sub(r"-\d{8}$", "", mid[7:]).split("-")
    names = [p[0].upper() + p[1:] for p in parts if re.search(r"[a-z]", p, re.I)]
    nums = [p for p in parts if p.isdigit()]
    return " ".join(names) + (" " + ".".join(nums) if nums else "")


def parse_claude(path):
    for line in lines(path):
        if '"usage"' not in line and "rate_limit" not in line:
            continue
        d = loads(line)
        m = d.get("message") if d else None
        if not isinstance(m, dict) or d.get("type") != "assistant":
            continue
        t = ts(d.get("timestamp"))
        if t is None:
            continue
        model = m.get("model")
        if model == "<synthetic>":
            # 额度用满时 Claude Code 写的一条提示，带重置时间
            if d.get("error") != "rate_limit":
                continue
            q = d.get("quotaLimits") or {}
            content = m.get("content")
            txt = str(content[0].get("text", "")) if isinstance(content, list) and content and isinstance(content[0], dict) else ""
            typ = q.get("rateLimitType") or ("seven_day" if re.search("weekly", txt, re.I) else "five_hour" if re.search("session limit", txt, re.I) else "")
            if not typ:
                continue
            rm = re.search(r"resets\s+([^(·]+)", txt, re.I)
            yield {"t": t, "limit": typ, "reset_at": q.get("resetsAt") or 0, "reset_text": rm.group(1).strip() if rm else "",
                   "key": f"limit|{typ}|{q.get('resetsAt') or txt}"}
            continue
        u = m.get("usage")
        if not isinstance(u, dict) or not model:
            continue
        cc = u.get("cache_creation") or {}
        w1h = cc.get("ephemeral_1h_input_tokens") or 0
        if cc.get("ephemeral_5m_input_tokens") is not None:
            w5 = cc["ephemeral_5m_input_tokens"]
        else:
            w5 = max(0, (u.get("cache_creation_input_tokens") or 0) - w1h)
        mid, rid = m.get("id"), d.get("requestId")
        yield {"t": t, "key": f"{mid}|{rid}" if mid and rid else d.get("uuid"), "sid": d.get("sessionId") or "", "model": model,
               "fast": u.get("speed") == "fast", "in": u.get("input_tokens") or 0, "out": u.get("output_tokens") or 0,
               "read": u.get("cache_read_input_tokens") or 0, "w5": w5, "w1h": w1h}


def parse_codex(path):
    prev, model, sid = None, "unknown", ""
    for line in lines(path):
        if not any(k in line for k in ('"token_count"', '"turn_context"', '"session_meta"')):
            continue
        d = loads(line)
        if not d:
            continue
        p = d.get("payload") or {}
        if d.get("type") == "session_meta":
            sid = p.get("id") or p.get("session_id") or sid
            continue
        if d.get("type") == "turn_context":
            model = p.get("model") or model
            continue
        if d.get("type") != "event_msg" or p.get("type") != "token_count":
            continue
        t = ts(d.get("timestamp"))
        if t is None:
            continue
        quota = []
        rl = p.get("rate_limits") or {}
        for k in ("primary", "secondary"):
            q = rl.get(k)
            if q and q.get("used_percent") is not None:
                quota.append({"minutes": q.get("window_minutes") or 0, "used": q["used_percent"], "reset_at": q.get("resets_at") or 0})
        usage = None
        info = p.get("info") or {}
        tot = info.get("total_token_usage")
        # 累计值逐条相减；同一个值会重复写，没变就不算
        if tot and (prev is None or tot.get("total_tokens") != prev.get("total_tokens")):
            last = info.get("last_token_usage")
            u = last or tot
            if prev is not None:
                u = {"input_tokens": (tot.get("input_tokens") or 0) - (prev.get("input_tokens") or 0),
                     "cached_input_tokens": (tot.get("cached_input_tokens") or 0) - (prev.get("cached_input_tokens") or 0),
                     "output_tokens": (tot.get("output_tokens") or 0) - (prev.get("output_tokens") or 0)}
                if u["input_tokens"] < 0 or u["output_tokens"] < 0:
                    u = last or tot
            prev = tot
            cached = min(u.get("cached_input_tokens") or 0, u.get("input_tokens") or 0)
            usage = {"model": model, "sid": sid, "key": f"codex|{sid}|{tot.get('total_tokens')}" if sid else None,
                     "in": (u.get("input_tokens") or 0) - cached, "read": cached, "out": u.get("output_tokens") or 0}
        if usage or quota:
            yield {"t": t, "usage": usage, "quota": quota}


def parse_wb(path):
    for line in lines(path):
        if '"providerData"' not in line:
            continue
        d = loads(line)
        p = d.get("providerData") if d else None
        if not isinstance(p, dict) or not (p.get("rawUsage") or p.get("usage")):
            continue
        t = ts(d.get("timestamp"))
        if t is None:
            continue
        r, u = p.get("rawUsage") or {}, p.get("usage") or {}
        inp = r["prompt_tokens"] if r.get("prompt_tokens") is not None else (u.get("inputTokens") or 0)
        details = u.get("inputTokensDetails") or []
        hit = max(r.get("prompt_cache_hit_tokens") or 0, (r.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                  r.get("cache_read_input_tokens") or 0, (details[0] if details else {}).get("cached_tokens") or 0)
        out = r["completion_tokens"] if r.get("completion_tokens") is not None else (u.get("outputTokens") or 0)
        yield {"t": t, "key": p.get("messageId") or d.get("id"), "sid": d.get("sessionId") or "",
               "model": p.get("model") or p.get("requestModelId") or "unknown", "name": p.get("requestModelName") or "",
               "in": max(0, inp - hit), "hit": min(hit, inp), "out": out}


def jsonl_under(roots, since):
    for root in roots:
        root = expand(root)
        if not root.is_dir():
            continue
        for p in root.rglob("*.jsonl"):
            try:
                if p.stat().st_mtime >= since:
                    yield p
            except OSError:
                pass


def dedupe(rows, start, end):
    """同一个 key 只留一行；还在写的回复 output 可能偏小，取最大的。"""
    seen, out = {}, []
    for r in rows:
        if not (start <= r["t"] < end):
            continue
        k = r.get("key")
        if k and k in seen:
            seen[k]["out"] = max(seen[k].get("out", 0), r.get("out", 0))
            continue
        out.append(r)
        if k:
            seen[k] = r
    return out


class Section:
    def __init__(self, priced):
        self.priced = priced
        self.models, self.sids = {}, set()

    def add(self, r, label, model, parts, n=1):
        m = self.models.setdefault(model, {"label": label, "priced": True, "reqs": 0, "lines": {}})
        m["reqs"] += n
        if r.get("sid"):
            self.sids.add(r["sid"])
        if self.priced and any(rate is None for _, _, rate in parts):
            m["priced"] = False
        for name, tokens, rate in parts:
            if not tokens:
                continue
            tot = m["lines"].setdefault(name, [0, 0.0])
            tot[0] += tokens
            tot[1] += tokens * (rate or 0) / M

    @property
    def tokens(self):
        return sum(v[0] for m in self.models.values() for v in m["lines"].values())

    @property
    def cost(self):
        return sum(v[1] for m in self.models.values() if m["priced"] for v in m["lines"].values())

    @property
    def requests(self):
        return sum(m["reqs"] for m in self.models.values())


def claude_parts(r):
    """一条 Claude 用量 → 各明细的 (名字, token 数, 每百万 token 价格)；查不到价格的模型价格为 None。"""
    p = price_of(r["model"])
    mult = (p.get("fast", 1) if r["fast"] else 1) if p else 1
    anthropic = r["model"].startswith("claude-")
    return [("input", r["in"], p["in"] * mult if p else None),
            ("output", r["out"], p["out"] * mult if p else None),
            ("read", r["read"], (p.get("read", p["in"] * 0.1)) * mult if p else None),
            ("write5", r["w5"], p["in"] * 1.25 * mult if p and anthropic else None),
            ("write1h", r["w1h"], p["in"] * 2 * mult if p and anthropic else None)]


def codex_parts(r):
    p = price_of(r["model"])
    return [("input", r["in"], p["in"] if p else None),
            ("read", r["read"], (p.get("read", p["in"] * 0.1)) if p else None),
            ("output", r["out"], p["out"] if p else None)]


# --demo 用的虚构数据：一个并不存在的工作日，只用来展示小票长什么样，不读任何本机日志
DEMO_CLAUDE = [  # 模型, 请求数, 输入, 输出, 缓存读, 缓存写 5m, 缓存写 1h
    ("claude-opus-5-5", 320, 800_000, 300_000, 40_000_000, 1_200_000, 900_000),
    ("claude-sonnet-5-5", 510, 1_100_000, 380_000, 90_000_000, 1_400_000, 700_000),
    ("claude-haiku-5-5", 40, 50_000, 30_000, 2_000_000, 0, 150_000),
]
DEMO_CODEX = [  # 模型, 请求数, 输入, 缓存读, 输出
    ("gpt-5.5", 180, 900_000, 30_000_000, 200_000),
    ("gpt-5.4-mini", 60, 300_000, 8_000_000, 90_000),
]
DEMO_WB = [("Hy4 preview", 200, 1_500_000, 20_000_000, 150_000)]  # 名字, 请求数, 输入, 缓存命中, 输出
DEMO_DATE = dt.date(2026, 10, 23)


def demo_data():
    claude, codex, wb = Section(True), Section(True), Section(False)
    for model, n, i, o, rd, w5, w1h in DEMO_CLAUDE:
        r = {"model": model, "fast": False, "in": i, "out": o, "read": rd, "w5": w5, "w1h": w1h}
        claude.add(r, model_label(model), model, claude_parts(r), n=n)
    for model, n, i, rd, o in DEMO_CODEX:
        codex.add({}, model, model, codex_parts({"model": model, "in": i, "read": rd, "out": o}), n=n)
    for name, n, i, hit, o in DEMO_WB:
        wb.add({}, name, name, [("input", i, 0), ("hit", hit, 0), ("output", o, 0)], n=n)
    claude.sids.update(f"demo-c{k}" for k in range(14))
    codex.sids.update(f"demo-x{k}" for k in range(19))
    wb.sids.update(f"demo-w{k}" for k in range(5))
    limits = {"five_hour": [{"t": 0, "reset_at": 0, "reset_text": h} for h in ("09:00", "14:00", "19:50")],
              "seven_day": [{"t": 0, "reset_at": 0, "reset_text": "10-30 06:00"}]}
    reset = dt.datetime(2026, 10, 30, 10, 50).timestamp()
    quota = {"quota": [{"minutes": 10080, "used": 36, "reset_at": reset}]}
    return {"claude": claude, "codex": codex, "wb": wb, "limits": limits, "codex_quota": quota}


def build(day_start, day_end, since):
    claude_rows = []
    for p in jsonl_under([SOURCES["claude"]], since):
        claude_rows += list(parse_claude(p))
    claude_rows = dedupe(claude_rows, day_start, day_end)
    wb_rows = []
    for p in jsonl_under([SOURCES["wb"]], since):
        wb_rows += list(parse_wb(p))
    wb_rows = dedupe(wb_rows, day_start, day_end)
    codex_rows = []
    for p in jsonl_under([SOURCES["codex"], CODEX_ARCHIVE], since):
        codex_rows += list(parse_codex(p))
    codex_usage = dedupe([r["usage"] | {"t": r["t"]} for r in codex_rows if r["usage"]], day_start, day_end)
    codex_quota = max((r for r in codex_rows if r["quota"] and day_start <= r["t"] < day_end), key=lambda r: r["t"], default=None)

    claude = Section(True)
    limits = {}
    for r in claude_rows:
        if "limit" in r:
            typ = r["limit"] if r["limit"] in ("five_hour", "seven_day") else "other"
            limits.setdefault(typ, []).append(r)
            continue
        claude.add(r, model_label(r["model"]), r["model"], claude_parts(r))

    codex = Section(True)
    for r in codex_usage:
        codex.add(r, r["model"], r["model"], codex_parts(r))

    wb = Section(False)
    for r in wb_rows:
        wb.add(r, r["name"] or r["model"], r["model"], [("input", r["in"], 0), ("hit", r["hit"], 0), ("output", r["out"], 0)])

    return {"claude": claude, "codex": codex, "wb": wb, "limits": limits, "codex_quota": codex_quota}


def fmt_usd(v):
    return f"${v:,.2f}"


def local_hm(epoch):
    return dt.datetime.fromtimestamp(epoch).strftime("%H:%M") if epoch else ""


def esc(s):
    return html.escape(str(s))


def row(label, tokens=None, amount=None, cls="", indent=True):
    t = f"{tokens:,}" if tokens is not None else ""
    a = esc(amount) if amount is not None else ""
    pad = "pl" if indent else ""
    return f'<div class="row {cls}"><span class="{pad}">{esc(label)}</span><span class="num">{t}</span><span class="amt">{a}</span></div>'


def section_html(key, sec, data, tr):
    has_limit = key == "claude" and data["limits"]
    has_quota = key == "codex" and data["codex_quota"]
    if not sec.models and not has_limit and not has_quota:
        return ""
    out = [f'<div class="sec"><div class="row head"><span>{esc(SECTION_NAMES[key])}</span><span></span>'
           f'<span class="sub">{esc(tr["sessions"].format(n=len(sec.sids), m=f"{sec.requests:,}"))}</span></div>']
    if sec.models:
        out.append(f'<div class="row cols sub"><span>{esc(tr["item"])}</span><span class="num">TOKEN</span><span class="amt">{esc(tr["amount"])}</span></div>')
    ordered = sorted(sec.models.values(), key=lambda m: -sum(v[1] for v in m["lines"].values())) if sec.priced else list(sec.models.values())
    for m in ordered:
        out.append(f'<div class="row bold"><span>{esc(m["label"])}</span><span></span>'
                   f'<span class="sub">{esc(tr["times"].format(n=f"{m["reqs"]:,}"))}</span></div>')
        for lk in LINE_ORDER[key]:
            if lk not in m["lines"]:
                continue
            tok, cost = m["lines"][lk]
            amount = (fmt_usd(cost) if m["priced"] else tr["unpriced_mark"]) if sec.priced else None
            out.append(row(tr[lk], tok, amount))
    if sec.models:
        out.append(row(tr["subtotal"], sec.tokens, fmt_usd(sec.cost) if sec.priced else tr["not_priced"], cls="bold", indent=False))
    if has_limit:
        for typ in ("five_hour", "seven_day", "other"):
            hits = data["limits"].get(typ)
            if not hits:
                continue
            hits.sort(key=lambda r: r["t"])
            resets = " · ".join(r["reset_text"] or local_hm(r["reset_at"]) for r in hits if r["reset_text"] or r["reset_at"])
            out.append(row(tr["limit"][typ], None, tr["times"].format(n=len(hits)), cls="bold", indent=False))
            if resets:
                out.append(f'<div class="row sub small"><span>{esc(tr["resets"])} {esc(resets)}</span></div>')
    if has_quota:
        names = {300: "five_hour", 10080: "seven_day"}
        for w in data["codex_quota"]["quota"]:
            out.append(row(tr["quota"][names.get(w["minutes"], "other")], None, f'{w["used"]:g}%', cls="bold", indent=False))
            if w["reset_at"]:
                out.append(f'<div class="row sub small"><span>{esc(tr["resets"])} {dt.datetime.fromtimestamp(w["reset_at"]).strftime("%m-%d %H:%M")}</span></div>')
    out.append("</div>")
    return "\n".join(out)


def barcode(seed):
    bits = "".join(f"{b:08b}" for b in hashlib.sha1(seed.encode()).digest())[:72]
    rects = "".join(f'<rect x="{i * 2}" y="0" width="1.2" height="40"/>' for i, b in enumerate(bits) if b == "1")
    return f'<svg class="bc" viewBox="0 0 144 40" preserveAspectRatio="none" aria-hidden="true">{rects}</svg>'


def local_host():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # 只为取本机出口地址，不发包
            ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    sysv = f"macOS {platform.mac_ver()[0]}" if platform.system() == "Darwin" else platform.platform()
    return ip, sysv


def zigzag_clip(n=28):
    """小票底边的锯齿，用 clip-path 切出来。"""
    pts = []
    for k in range(n):
        x0 = 100 - k * 100 / n
        pts.append(f"{x0:.2f}% calc(100% - 12px)")
        pts.append(f"{x0 - 50 / n:.2f}% 100%")
    pts.append("0% calc(100% - 12px)")
    return "polygon(0 0, 100% 0, 100% calc(100% - 12px), " + ", ".join(pts) + ")"


CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
html, body { margin: 0; }
body { font: 12px/1.55 ui-monospace, "SF Mono", Menlo, "PingFang SC", monospace; color: #222; background: #e9e4da; }
.stage { position: relative; min-height: 100vh; padding: 40px 16px; display: flex; flex-direction: column;
  align-items: center; overflow: hidden; }
.drop { position: relative; width: 380px; max-width: 100%; filter: drop-shadow(0 10px 14px rgba(0,0,0,.28));
  animation: drop 1.1s cubic-bezier(.2,.8,.3,1.1) both; transform: rotate(var(--tilt, 0deg)); }
.paper { position: relative; width: 100%; padding: 22px 20px 26px; background: #fbfaf6; clip-path: __ZIG__; }
.c { text-align: center; }
.title { font-size: 20px; font-weight: 700; letter-spacing: .12em; margin-top: 6px; }
.row { display: flex; justify-content: space-between; gap: 8px; }
.row .num { text-align: right; white-space: nowrap; }
.row .amt { text-align: right; white-space: nowrap; min-width: 4.5em; }
.pl { padding-left: 1em; }
.bold { font-weight: 700; }
.sub { color: #777; }
.small { font-size: 11.5px; }
.sec { margin: 6px 0; }
.hr { border-top: 1px dashed #999; margin: 10px 0; }
.dbl { border-top: 3px double #555; margin: 10px 0; }
.foot { margin-top: 14px; font-size: 11.5px; color: #777; text-align: center; }
.bc { display: block; width: 100%; height: 40px; margin: 12px 0 2px; fill: #222; }

/* 场景底纹 */
.s-desk { background: repeating-linear-gradient(92deg, rgba(60,30,10,.10) 0 2px, transparent 2px 11px),
  repeating-linear-gradient(0deg, rgba(255,220,170,.05) 0 1px, transparent 1px 7px), linear-gradient(180deg, #9b6b42, #6a4426); }
.s-cork { background: radial-gradient(circle at 30% 40%, rgba(90,50,20,.35) 0 1px, transparent 1.6px) 0 0 / 7px 7px,
  radial-gradient(circle at 70% 60%, rgba(255,230,190,.35) 0 1px, transparent 1.6px) 0 0 / 11px 11px, #b98752; }
.s-tape { background: linear-gradient(90deg, transparent 58px, #e7a4a4 58px 59px, transparent 59px),
  repeating-linear-gradient(180deg, transparent 0 27px, #c9d6ea 27px 28px), #f6f5ee; }
.s-clip { background: #6d6a66; }
.s-plain { background: #f1efe9; }
.s-printer { justify-content: flex-end; background: linear-gradient(180deg, #d7d1c5, #c4bdb0); }

/* 场景：桌面 / 软木 / 手账 带倾角落下；账单夹板从下方滑入 */
.s-desk .drop { --tilt: .8deg; }
.s-cork .drop { --tilt: -1.4deg; }
.s-tape .drop { --tilt: .6deg; }
.s-clip .drop { animation-name: slide; transform: none; }
.s-plain .drop { animation-name: fade; transform: none; filter: drop-shadow(0 6px 10px rgba(0,0,0,.14)); }

.pin { position: absolute; top: -8px; width: 16px; height: 16px; border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, #ff8a80, #c62828 60%, #7f0000); box-shadow: 0 2px 3px rgba(0,0,0,.4);
  animation: pop .35s .9s both; }
.tape-strip { position: absolute; top: -12px; width: 110px; height: 30px; background: rgba(245,238,210,.78);
  box-shadow: 0 1px 2px rgba(0,0,0,.15); animation: pop .4s .9s both; }
.clip-bar { position: absolute; top: -20px; left: 50%; margin-left: -62px; width: 124px; height: 36px; border-radius: 7px;
  background: linear-gradient(180deg, #eceef1, #9ea3aa); box-shadow: 0 2px 4px rgba(0,0,0,.35); animation: pop .4s .9s both; }
.board { position: absolute; top: 0; bottom: 0; left: 50%; width: 460px; margin-left: -230px; background: linear-gradient(180deg, #e9e6df, #d3cfc6);
  border-radius: 10px; box-shadow: inset 0 0 0 1px rgba(0,0,0,.12); }

/* 热敏打印机：纸从出纸口向上吐出 */
.feed { width: 380px; max-width: 100%; overflow: hidden; }
.feed .paper { filter: none; animation: feed 2.2s cubic-bezier(.3,.6,.4,1) both; }
.printer { position: relative; width: 420px; max-width: 100%; height: 120px; margin-bottom: 40px;
  background: linear-gradient(180deg, #363a3f, #1b1e22); border-radius: 16px 16px 8px 8px; box-shadow: 0 10px 24px rgba(0,0,0,.35); }
.slot { position: absolute; left: 28px; right: 28px; top: -3px; height: 8px; background: #050505; border-radius: 4px; }
.model { position: absolute; left: 28px; bottom: 24px; color: #7d838a; font-weight: 700; letter-spacing: .08em; }
.model small { display: block; font-weight: 400; font-size: 9px; color: #5a6066; }
.leds { position: absolute; right: 28px; bottom: 24px; font-size: 10px; color: #6c727a; text-align: left; }
.led { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #333; margin-right: 6px; }
.led.on { background: #4cd964; box-shadow: 0 0 6px #4cd964; }
.confetti { position: absolute; left: 50%; bottom: 170px; width: 0; height: 0; }
.confetti i { position: absolute; width: 8px; height: 5px; border-radius: 1px; opacity: 0; animation: burst 1.4s ease-out both; }

@keyframes drop { 0% { transform: translateY(-70vh) rotate(-8deg); opacity: 0; }
  60% { opacity: 1; } 80% { transform: translateY(8px) rotate(var(--tilt, 0deg)); }
  100% { transform: translateY(0) rotate(var(--tilt, 0deg)); } }
@keyframes slide { from { transform: translateY(45vh); opacity: 0; } to { transform: none; opacity: 1; } }
@keyframes fade { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@keyframes feed { from { transform: translateY(100%); } to { transform: none; } }
@keyframes pop { from { transform: scale(.2); opacity: 0; } to { transform: scale(1); opacity: 1; } }
@keyframes burst { 0% { opacity: 0; transform: translate(0, 0) rotate(0); } 15% { opacity: 1; }
  100% { opacity: 0; transform: translate(var(--dx), var(--dy)) rotate(260deg); } }

@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; } }
html[data-static] *, html[data-static] *::before, html[data-static] *::after { animation: none !important; }
html[data-static] .confetti { display: none; }

@media print {
  @page { size: 80mm auto; margin: 0; }
  body { background: #fff; }
  .stage { background: none !important; min-height: 0; padding: 0; }
  .printer, .board, .clip-bar, .pin, .tape-strip, .confetti { display: none; }
  .drop { width: 80mm; max-width: none; transform: none; animation: none; filter: none; }
  .paper { padding: 4mm; }
  .feed { width: 80mm; }
}
""".replace("__ZIG__", zigzag_clip())


def confetti(seed):
    rnd = random.Random(seed)
    colors = ["#e74c3c", "#16a085", "#8e44ad", "#3498db", "#f1c40f", "#e67e22"]
    pieces = []
    for _ in range(16):
        pieces.append(f'<i style="left:{rnd.randint(-200, 200)}px;top:{rnd.randint(-160, -20)}px;background:{rnd.choice(colors)};'
                      f'--dx:{rnd.randint(-40, 40)}px;--dy:{rnd.randint(-30, 30)}px;animation-delay:{2.2 + rnd.random() * 0.4:.2f}s"></i>')
    return '<div class="confetti">' + "".join(pieces) + "</div>"


def stage_html(scene, paper, seed):
    if scene == "printer":
        return (f'<div class="stage s-printer"><div class="feed">{paper}</div>'
                '<div class="printer"><div class="slot"></div>'
                '<div class="model">TR-80<small>THERMAL RECEIPT PRINTER</small></div>'
                '<div class="leds"><span class="led on"></span>POWER<br><span class="led"></span>ERROR<br><span class="led"></span>PAPER</div>'
                "</div>" + confetti(seed) + "</div>")
    extra = {
        "desk": "",
        "cork": '<i class="pin" style="left:18px"></i><i class="pin" style="right:18px"></i>',
        "tape": '<i class="tape-strip" style="left:-10px;transform:rotate(-6deg)"></i>'
                '<i class="tape-strip" style="right:-10px;transform:rotate(7deg)"></i>',
        "clip": '<div class="clip-bar"></div>',
        "plain": "",
    }[scene]
    board = '<div class="board"></div>' if scene == "clip" else ""
    return f'<div class="stage s-{scene}">{board}<div class="drop">{paper}{extra}</div></div>'


def render(args, data, day, now, lang, scene, static):
    tr = I18N[lang]
    claude, codex, wb = data["claude"], data["codex"], data["wb"]
    total_tok = claude.tokens + codex.tokens + wb.tokens
    total_cost = claude.cost + codex.cost
    unpriced = any(not m["priced"] for s in (claude, codex) for m in s.models.values())
    receipt_no = f"{day:%Y%m%d}-{now:%H%M}"
    wd = tr["weekday"][day.weekday()]
    date_line = tr["date"].format(d=f"{day:%Y-%m-%d}", w=wd)
    host_line = ""
    if args.host:
        ip, sysv = local_host()
        host_line = f'<div class="row sub small"><span>{esc(tr["table"])} {esc(ip)}</span><span>{esc(tr["seat"])} {esc(sysv)}</span></div>'
    body = [
        '<div class="paper">',
        f'<div class="c"><div class="title">{esc(tr["title"])}</div><div class="sub">{esc(tr["subtitle"])}</div>'
        f'<div class="sub">{esc(date_line)}</div></div>',
        '<div class="hr"></div>',
        f'<div class="row sub small"><span>{esc(tr["no"])} #{receipt_no}</span><span>{esc(tr["printed"])} {now:%H:%M}</span></div>',
        host_line,
        '<div class="hr"></div>',
    ]
    secs = [s for s in (section_html(k, data[k], data, tr) for k in ("claude", "codex", "wb")) if s]
    if not secs:
        body.append(f'<div class="c sub">{esc(tr["none"])}</div>')
    for i, s in enumerate(secs):
        body.append(s)
        if i < len(secs) - 1:
            body.append('<div class="hr"></div>')
    body += [
        '<div class="dbl"></div>',
        row(tr["total"], total_tok, None, cls="bold", indent=False),
        row(tr["api"], None, fmt_usd(total_cost), cls="bold", indent=False),
        '<div class="hr"></div>',
        f'<div class="foot">{esc(tr["note"])}' + (f"<br>{esc(tr['unpriced_note'])}" if unpriced else "") + "</div>",
        barcode(receipt_no),
        f'<div class="c small">{esc(receipt_no)}</div>',
        f'<div class="c" style="margin-top:8px">{esc(tr["thanks"])}</div>',
    ]
    paper = "\n".join(body) + "</div>"
    attr = " data-static" if static else ""
    return (f'<!doctype html><html lang="{tr["lang"]}"{attr}><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(tr['title'])} {day:%Y-%m-%d}</title><style>{CSS}</style></head><body>"
            + stage_html(scene, paper, receipt_no) + "</body></html>\n")


PRICE_URL = "https://openrouter.ai/api/v1/models"  # 公开接口，无需密钥，只拉价目表
PRICE_CACHE = expand("~/.cache/token-receipt/openrouter-models.json")
PRICE_TTL = 24 * 3600
# 随仓库附带的价格快照（只含 PRICES 里的模型），离线时使用；用 --export-prices 重新生成
SNAPSHOT = Path(__file__).resolve().parent / "prices" / "openrouter-snapshot.json"


def snapshot_models():
    if not SNAPSHOT.exists():
        return None
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    print(f"（离线：使用随仓库附带的价格快照，抓取于 {data.get('fetched_at', '未知')}）")
    return data.get("models", [])


def remote_models():
    """OpenRouter 的模型价目表，本地缓存一天；联网失败时退回随仓库附带的快照，两者都没有则返回 None。"""
    if PRICE_CACHE.exists() and time.time() - PRICE_CACHE.stat().st_mtime < PRICE_TTL:
        return json.loads(PRICE_CACHE.read_text(encoding="utf-8"))
    try:
        with urllib.request.urlopen(PRICE_URL, timeout=15) as resp:
            models = json.load(resp).get("data", [])
    except (OSError, urllib.error.URLError, ValueError):
        return snapshot_models()
    PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PRICE_CACHE.write_text(json.dumps(models), encoding="utf-8")
    return models


def export_prices():
    """把 PRICES 里每个模型在 OpenRouter 上的价格写成快照，随仓库一起发布。"""
    models = remote_models()
    if models is None:
        raise SystemExit("无法访问 OpenRouter，也没有可用的快照，无法导出")
    wanted = {or_id(k) for k in PRICES}
    picked = [{"id": m["id"], "pricing": m.get("pricing", {})} for m in models if m.get("id") in wanted]
    missing = sorted(wanted - {m["id"] for m in picked})
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps({"fetched_at": dt.date.today().isoformat(), "source": PRICE_URL, "models": picked},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {SNAPSHOT}：{len(picked)} 个模型")
    if missing:
        print("OpenRouter 上没有：" + "、".join(missing))


def or_id(model):
    """本地模型名 → OpenRouter 的 id：claude-opus-5-5 → anthropic/claude-opus-5.5，gpt-5.5 → openai/gpt-5.5。"""
    if "/" in model:  # 已带厂商前缀，如 deepseek/deepseek-v4-pro
        return model
    m = re.sub(r"-(\d{8}|\d{4}-\d{2}-\d{2})$", "", model)
    m = re.sub(r"^(claude-.+)-(\d+)-(\d+)$", r"anthropic/\1-\2.\3", m)
    if m.startswith("claude-"):
        m = "anthropic/" + m
    if m.startswith("gpt-"):
        m = "openai/" + m
    return m


def per_m(v):
    """OpenRouter 给的是每 token 的字符串价格，换成美元每百万 token。"""
    return None if v in (None, "") else round(float(v) * M, 6)


def remote_price(model, models):
    oid = or_id(model)
    for m in models:
        if m.get("id") == oid:
            p = m.get("pricing") or {}
            return {"id": oid, "in": per_m(p.get("prompt")), "out": per_m(p.get("completion")),
                    "read": per_m(p.get("input_cache_read")), "w5": per_m(p.get("input_cache_write")),
                    "w1h": per_m(p.get("input_cache_write_1h")), "long": p.get("overrides") or []}
    return None


def local_price(model):
    p = price_of(model)
    if not p:
        return None
    claude = model.startswith("claude-")  # 缓存写只有 Anthropic 收费
    return {"in": p["in"], "out": p["out"], "read": p.get("read", p["in"] * 0.1),
            "w5": p["in"] * 1.25 if claude else None, "w1h": p["in"] * 2 if claude else None, "fast": p.get("fast")}


def fmt_p(v):
    return "—" if v is None else f"{v:g}"


def show_prices(models_to_query):
    models = remote_models()
    if models is None:
        print("无法访问 OpenRouter，只显示本地价目表（网络恢复后重试）")
    for model in models_to_query:
        loc = local_price(model)
        rem = remote_price(model, models) if models is not None else None
        print(f"\n{model}  →  {rem['id'] if rem else or_id(model) + '（未找到）'}")
        print(f"  {'':<12}{'输入':>8}{'输出':>8}{'缓存读':>8}{'写5m':>8}{'写1h':>8}   $/百万 token")
        if rem:
            print(f"  {'OpenRouter':<12}" + "".join(f"{fmt_p(rem[k]):>10}" for k in ("in", "out", "read", "w5", "w1h")))
            for o in rem["long"]:
                print(f"  {'  长上下文':<12}输入 {fmt_p(per_m(o.get('prompt')))} · 输出 {fmt_p(per_m(o.get('completion')))}"
                      f"（prompt ≥ {o.get('min_prompt_tokens', 0):,} token 时）")
        if loc:
            print(f"  {'本地表':<12}" + "".join(f"{fmt_p(loc[k]):>10}" for k in ("in", "out", "read", "w5", "w1h"))
                  + (f"   快速模式 ×{loc['fast']}" if loc.get("fast") else ""))
        if rem and loc:
            diffs = [k for k in ("in", "out", "read") if rem[k] is not None and loc[k] is not None and abs(rem[k] - loc[k]) > 1e-9]
            print("  ⚠ 与本地表不一致：" + "、".join({"in": "输入", "out": "输出", "read": "缓存读"}[k] for k in diffs) if diffs else "  与本地表一致")


def check_prices():
    models = remote_models()
    if models is None:
        print("无法访问 OpenRouter，无法校对")
        return
    for model in PRICES:
        loc, rem = local_price(model), remote_price(model, models)
        if rem is None:
            print(f"{model}: OpenRouter 上没有，跳过")
            continue
        bad = [(k, loc[k], rem[k]) for k in ("in", "out", "read") if rem[k] is not None and abs(rem[k] - loc[k]) > 1e-9]
        for k, a, b in bad:
            print(f"{model}: {k} 本地 {fmt_p(a)} / OpenRouter {fmt_p(b)}")
    print("校对完成")


CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_chrome():
    """优先用环境变量 TOKEN_RECEIPT_CHROME 指定的浏览器，否则在常见位置里找。"""
    for c in [os.environ.get("TOKEN_RECEIPT_CHROME")] + CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    return None


def render_png(html_path, png_path, height):
    """用本机 Chrome 无头模式截图；没有 Chrome 时返回 False。"""
    chrome = find_chrome()
    if not chrome:
        return False
    cmd = [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
           f"--window-size=480,{height}", f"--screenshot={png_path}", html_path.resolve().as_uri()]
    res = subprocess.run(cmd, capture_output=True, timeout=120)
    return res.returncode == 0 and png_path.exists()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD，缺省今天（本机时区）")
    ap.add_argument("--lang", choices=("zh", "en", "all"), default="zh", help="小票语言，all 中英各一份")
    ap.add_argument("--scene", choices=SCENES + ("all",), default="printer", help="场景，all 一次出六种")
    ap.add_argument("--out", help="输出目录，缺省 ~/Downloads")
    ap.add_argument("--host", action="store_true", help="在小票上印本机局域网 IP 和系统版本（分享前注意）")
    ap.add_argument("--no-png", action="store_true", help="只出 HTML，不用 Chrome 渲染 PNG")
    ap.add_argument("--height", type=int, default=1300, help="PNG 视窗高度（像素），小票太长时调大")
    ap.add_argument("--price", nargs="+", metavar="MODEL", help="查询模型实际价格（OpenRouter 与本地表对照），不出小票")
    ap.add_argument("--check-prices", action="store_true", help="校对本地价目表与 OpenRouter，列出不一致的项")
    ap.add_argument("--export-prices", action="store_true", help="把 PRICES 的 OpenRouter 价格写成快照 prices/openrouter-snapshot.json")
    ap.add_argument("--demo", action="store_true", help="用虚构的一天出小票（不读本机日志），用来预览场景与版式")
    args = ap.parse_args()

    if args.price:
        show_prices(args.price)
        return
    if args.check_prices:
        check_prices()
        return
    if args.export_prices:
        export_prices()
        return

    if args.demo:
        now, day, data = dt.datetime(2026, 10, 23, 18, 23).astimezone(), DEMO_DATE, demo_data()
    else:
        now = dt.datetime.now().astimezone()
        day = dt.date.fromisoformat(args.date) if args.date else now.date()
        day_start = dt.datetime.combine(day, dt.time()).astimezone().timestamp()
        day_end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time()).astimezone().timestamp()
        data = build(day_start, day_end, day_start)

    out_dir = expand(args.out) if args.out else expand("~/Downloads")
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = SCENES if args.scene == "all" else (args.scene,)
    langs = ("zh", "en") if args.lang == "all" else (args.lang,)
    for lang, scene in [(lg, sc) for lg in langs for sc in scenes]:
        stem = f"token-receipt-{day:%Y-%m-%d}-{scene}-{lang}"
        out = out_dir / f"{stem}.html"
        out.write_text(render(args, data, day, now, lang, scene, static=False), encoding="utf-8")
        print(out)
        if args.no_png:
            continue
        # PNG 用静态版（关掉动画），截到的是落定后的画面
        static = out_dir / f"{stem}.static.html"
        static.write_text(render(args, data, day, now, lang, scene, static=True), encoding="utf-8")
        png = out_dir / f"{stem}.png"
        if render_png(static, png, args.height):
            print(png)
        else:
            print("未找到 Chrome，跳过 PNG（HTML 已生成）")
        static.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
