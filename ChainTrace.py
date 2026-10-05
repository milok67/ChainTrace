#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChainTrace 2.1 — находит и рисует цепочки прямых переводов между кошельками
(Bitcoin / Ethereum / TON). Библиотеки не нужны, Python 3.8+.
ChainTrace 2.1 — finds and draws chains of direct transfers between wallets.

Запуск / Run:
  python chaintrace.py                       — спросит язык и адреса / asks language and addresses
  python chaintrace.py АДРЕС1 АДРЕС2
  python chaintrace.py АДРЕС1                — без второго кошелька / single wallet
  python chaintrace.py --demo                — пример без интернета / offline demo
Ключи / flags: --lang ru|en, --expand 20, --limit 500, --days 180,
  --ton-key / --es-key / --token, --no-cache, --no-open
"""

import argparse
import base64
import hashlib
import html
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

VERSION = "2.1"
SYM = {"btc": "BTC", "eth": "ETH", "ton": "TON"}
NAME = {"btc": "Bitcoin", "eth": "Ethereum", "ton": "TON"}
EXPLORER = {"btc": "https://mempool.space/address/{}",
            "eth": "https://etherscan.io/address/{}",
            "ton": "https://tonviewer.com/{}"}
HUB_DEGREE = 150          # у кого столько контрагентов — скорее биржа/сервис

# ──────────────────────────── язык / language ────────────────────────────

LANG = "ru"

T = {
    "ru": {
        "w1": "Кошелёк 1", "w2": "Кошелёк 2", "w1s": "К1", "w2s": "К2",
        "prompt_w1": "Адрес кошелька 1 (или demo)",
        "prompt_w2": "Адрес кошелька 2 (Enter — пропустить)",
        "start_hint": "Вставьте адрес и нажмите Enter. Сеть определится сама.",
        "start_hint2": "Второй кошелёк — цель цепочки. Без него покажу окружение первого.",
        "all_history": "вся история", "last_days": "последние {d} дн", "demo": "демо",
        "s_load": "Истории кошельков", "s_cp": "Истории контрагентов",
        "s_find": "Поиск цепочек", "s_links": "Связи контрагентов",
        "cp_count": "контрагентов: {a}", "cp_count2": "контрагентов: {a} и {b}",
        "found_n": "найдено: {n}",
        "loading": "загрузка {addr}",
        "err_load": "Не удалось загрузить историю — {who}: {e}",
        "hint_api": "Проверьте интернет / VPN или добавьте ключ API: --ton-key / --es-key / --token",
        "warn_failed": "не загрузились истории {n} контрагентов — результат может быть неполным",
        "no_chains": "Цепочек от Кошелька 1 до Кошелька 2 не найдено (до 4 шагов).",
        "no_chains_hint": "Попробуйте: --expand 30 (больше контрагентов) или --limit 1000 (длиннее история)",
        "found": "Найдено цепочек: {n}", "showing": "показываю {n} лучших",
        "legend": "{d} деньги шли сверху вниз   {u} снизу вверх",
        "chain_title": "ЦЕПОЧКА #{k}", "weakest": "слабое звено: {w}",
        "hub": "[много контрагентов — биржа/сервис?]", "last": "посл.",
        "summary": "ИТОГ", "addresses": "АДРЕСА",
        "funded": "КТО ПОПОЛНЯЛ Кошелёк 1", "sent": "КУДА ОТПРАВЛЯЛ Кошелёк 1",
        "total": "всего {n}", "none": "нет",
        "links": "Связей между контрагентами: {n}",
        "link_title": "СВЯЗКА #{k}", "also": "{y} тоже напрямую связан с Кошельком 1:",
        "no_links": "Контрагенты между собой напрямую не переводили.",
        "html_saved": "Схемы в браузере: {p}",
        "done": "готово за {t} с · историй загружено: {n}",
        "nav": "Enter дальше · p назад · номер страницы · q выход",
        "nav_last": "Enter / q выход · p назад · номер страницы",
        "page": "{i}/{n}",
        "bad_net": "Не понял сеть (или кошельки из разных сетей). Укажите --chain btc|eth|ton",
        "same": "Адреса совпадают", "no_addr": "Адрес не введён",
        "interrupted": "прервано", "exit": "Enter — выход",
        "result_title": "ChainTrace · результат",
    },
    "en": {
        "w1": "Wallet 1", "w2": "Wallet 2", "w1s": "W1", "w2s": "W2",
        "prompt_w1": "Wallet 1 address (or demo)",
        "prompt_w2": "Wallet 2 address (Enter to skip)",
        "start_hint": "Paste an address and press Enter. The network is detected automatically.",
        "start_hint2": "Wallet 2 is the chain target. Without it, wallet 1's surroundings are shown.",
        "all_history": "full history", "last_days": "last {d} days", "demo": "demo",
        "s_load": "Wallet histories", "s_cp": "Counterparty histories",
        "s_find": "Searching chains", "s_links": "Counterparty links",
        "cp_count": "counterparties: {a}", "cp_count2": "counterparties: {a} and {b}",
        "found_n": "found: {n}",
        "loading": "loading {addr}",
        "err_load": "Could not load history — {who}: {e}",
        "hint_api": "Check internet / VPN or add an API key: --ton-key / --es-key / --token",
        "warn_failed": "{n} counterparty histories failed to load — results may be incomplete",
        "no_chains": "No chains from Wallet 1 to Wallet 2 found (up to 4 steps).",
        "no_chains_hint": "Try: --expand 30 (more counterparties) or --limit 1000 (longer history)",
        "found": "Chains found: {n}", "showing": "showing the best {n}",
        "legend": "{d} money flowed down the chain   {u} flowed up",
        "chain_title": "CHAIN #{k}", "weakest": "weakest link: {w}",
        "hub": "[many counterparties — exchange/service?]", "last": "last",
        "summary": "SUMMARY", "addresses": "ADDRESSES",
        "funded": "WHO FUNDED Wallet 1", "sent": "WHERE Wallet 1 SENT",
        "total": "{n} total", "none": "none",
        "links": "Links between counterparties: {n}",
        "link_title": "LINK #{k}", "also": "{y} is also directly linked to Wallet 1:",
        "no_links": "Counterparties never transferred to each other directly.",
        "html_saved": "Diagrams in browser: {p}",
        "done": "done in {t} s · histories loaded: {n}",
        "nav": "Enter next · p back · page number · q quit",
        "nav_last": "Enter / q quit · p back · page number",
        "page": "{i}/{n}",
        "bad_net": "Could not detect the network (or wallets are on different networks). Use --chain btc|eth|ton",
        "same": "Addresses are identical", "no_addr": "No address entered",
        "interrupted": "interrupted", "exit": "Enter to exit",
        "result_title": "ChainTrace · result",
    },
}

def tr(key, **kw):
    s = T[LANG].get(key, T["ru"][key])
    return s.format(**kw) if kw else s

def plural(n):
    if LANG == "en":
        return f"{n} transfer" + ("" if n == 1 else "s")
    return f"{n} " + _ru(n, ("перевод", "перевода", "переводов"))

def steps_word(n):
    if LANG == "en":
        return f"{n} step" + ("" if n == 1 else "s")
    return f"{n} " + _ru(n, ("шаг", "шага", "шагов"))

def _ru(n, forms):
    a, b = n % 10, n % 100
    if a == 1 and b != 11:
        return forms[0]
    if 2 <= a <= 4 and not 12 <= b <= 14:
        return forms[1]
    return forms[2]

# ──────────────────────────── консоль ────────────────────────────

def _enable_ansi():
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            m = ctypes.c_ulong()
            k.GetConsoleMode(h, ctypes.byref(m))
            k.SetConsoleMode(h, m.value | 0x4)
        except Exception:
            os.system("")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

def _can(chars):
    try:
        chars.encode(sys.stdout.encoding or "utf-8")
        return True
    except Exception:
        return False

UNI = _can("╭╮╰╯─│├└┌↓↑✔✘○●⠋…█░")
if UNI:
    B_TL, B_TR, B_BL, B_BR, B_H, B_V, B_ML, B_MR = "╭", "╮", "╰", "╯", "─", "│", "├", "┤"
    V, TOP, MID, BOT = "│", "┌", "├", "└"
    DOWN, UP, ARROW, OK, ERR, WAIT = "↓", "↑", "→", "✔", "✘", "○"
    SPIN, FULL, EMPTY, ELL, DOT = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "█", "░", "…", "·"
else:
    B_TL = B_TR = B_BL = B_BR = B_ML = B_MR = "+"
    B_H, B_V = "-", "|"
    V, TOP, MID, BOT = "|", "+", "+", "+"
    DOWN, UP, ARROW, OK, ERR, WAIT = "v", "^", "->", "+", "x", "o"
    SPIN, FULL, EMPTY, ELL, DOT = "|/-\\", "#", ".", "..", "-"

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

def col(t, code):
    return f"\033[{code}m{t}\033[0m" if COLOR else str(t)

def bold(t): return col(t, "1")
def gray(t): return col(t, "90")
def cyan(t): return col(t, "96")
def green(t): return col(t, "92")
def yellow(t): return col(t, "93")
def red(t): return col(t, "91")
def violet(t): return col(t, "95")

_RX_ANSI = re.compile(r"\033\[[0-9;]*m")

def vlen(s):
    return len(_RX_ANSI.sub("", str(s)))

def vfit(s, w):
    """Обрезает строку с цветами до видимой ширины w."""
    s = str(s)
    if vlen(s) <= w:
        return s
    out, vis, i = [], 0, 0
    while i < len(s) and vis < w - 1:
        m = _RX_ANSI.match(s, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        out.append(s[i])
        vis += 1
        i += 1
    return "".join(out) + ELL + ("\033[0m" if COLOR else "")

def bar(done, total, width=22):
    k = int(width * done / total) if total else width
    return cyan(FULL * k) + gray(EMPTY * (width - k)) + gray(f" {done}/{total}")

# ──────────────────────────── окно ────────────────────────────

class UI:
    """Одно окно в рамке, которое перерисовывается на месте (без спама в консоль).
    Если вывод не в терминал (файл/pipe) — просто печатает строки."""

    def __init__(self):
        self.live = sys.stdout.isatty() and sys.stdin.isatty()
        self.lock = threading.RLock()
        self.right = ""
        self.head = []          # шапка: кошельки, сеть
        self.steps = None       # [[state, text, detail], ...] — экран загрузки
        self.body = []          # строки страницы
        self.notes = []         # предупреждения под шагами
        self.status = ""
        self.foot = ""
        self._busy = False
        self._frame = 0
        self._last = 0.0
        self._thread = None

    # — служебное —
    def open(self):
        if self.live:
            sys.stdout.write("\033[?1049h\033[H\033[2J")
            sys.stdout.flush()

    def close(self):
        self.busy(False)
        if self.live:
            sys.stdout.write("\033[?1049l")
            sys.stdout.flush()

    def size(self):
        s = shutil.get_terminal_size((100, 30))
        return max(56, min(s.columns - 1, 118)), max(14, s.lines)

    def busy(self, on):
        self._busy = on
        if on and self.live and not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        if not on and self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None

    def _spin(self):
        while self._busy:
            self._frame += 1
            self.render(force=True)
            time.sleep(0.1)

    # — состояние —
    def step(self, i, state, detail=None):
        with self.lock:
            st = self.steps[i]
            st[0] = state
            if detail is not None:
                st[2] = detail
            if not self.live and state in ("done", "error"):
                mark = green(OK) if state == "done" else red(ERR)
                print(f"  {mark} {st[1]}" + (gray(f"  {DOT} {st[2]}") if st[2] else ""))
        self.render(force=True)

    def note(self, text):
        with self.lock:
            self.notes.append(text)
            if not self.live:
                print("  " + text)
        self.render(force=True)

    def set_status(self, text):
        self.status = text
        self.render()

    # — отрисовка —
    def _step_lines(self):
        out = []
        sp = SPIN[self._frame % len(SPIN)]
        for state, text, detail in self.steps:
            if state == "done":
                mark, t = green(OK), text
            elif state == "error":
                mark, t = red(ERR), red(text)
            elif state == "active":
                mark, t = cyan(sp), bold(text)
            else:
                mark, t = gray(WAIT), gray(text)
            out.append(f" {mark}  {t}" + (gray(f"   {DOT} ") + detail if detail else ""))
        if self.notes:
            out.append("")
            out += [" " + n for n in self.notes]
        return out

    def render(self, force=False):
        if not self.live:
            return
        with self.lock:
            now = time.time()
            if not force and now - self._last < 0.05:
                return
            self._last = now
            W, H = self.size()
            inner = W - 4

            def row(t=""):
                t = vfit(t, inner)
                return gray(B_V) + " " + t + " " * (inner - vlen(t)) + " " + gray(B_V)

            def sep():
                return gray(B_ML + B_H * (W - 2) + B_MR)

            name = f" ChainTrace {VERSION} "
            right = f" {self.right} " if self.right else ""
            fill = max(W - 3 - len(name) - vlen(right), 1)
            lines = [gray(B_TL + B_H) + bold(green(name)) + gray(B_H * fill) + gray(right) + gray(B_TR)]
            for h in self.head:
                lines.append(row(h))
            if self.head:
                lines.append(sep())
            body = self._step_lines() if self.steps is not None else list(self.body)
            room = H - len(lines) - 4 - (2 if self.status and self.steps is not None else 0)
            if len(body) > room:
                body = body[:max(room - 1, 1)] + [gray(f"  {ELL}")]
            lines.append(row())
            lines += [row(" " + b) for b in body]
            lines.append(row())
            if self.status and self.steps is not None:
                lines.append(sep())
                lines.append(row(gray(" " + self.status)))
            foot = f" {self.foot} " if self.foot else ""
            fill = max(W - 3 - vlen(foot), 1)
            lines.append(gray(B_BL + B_H) + gray(foot) + gray(B_H * fill) + gray(B_BR))
            sys.stdout.write("\033[H" + "\n".join(l + "\033[K" for l in lines) + "\n\033[J")
            sys.stdout.flush()

    def ask(self, prompt):
        """Строка ввода под окном."""
        self.render(force=True)
        try:
            return input(cyan(f" {ARROW} ") + bold(prompt) + gray(": ") if prompt else cyan(f" {ARROW} ")).strip()
        except EOFError:
            return "q"

    def pager(self, pages):
        """pages: [(заголовок, [строки])]. Листание: Enter / p / номер / q."""
        if not self.live:
            for title, lines in pages:
                print()
                print("  " + bold(title))
                for l in lines:
                    print("  " + l)
            return
        self.steps = None
        i = 0
        while True:
            title, lines = pages[i]
            self.body = [bold(title), ""] + lines
            last = i == len(pages) - 1
            self.foot = tr("page", i=i + 1, n=len(pages)) + f" {DOT} " + (tr("nav_last") if last else tr("nav"))
            cmd = self.ask("").lower()
            if cmd in ("q", "й", "0", "exit"):
                return
            if cmd in ("p", "з", "b", "и"):
                i = max(i - 1, 0)
            elif cmd.isdigit() and 1 <= int(cmd) <= len(pages):
                i = int(cmd) - 1
            elif last:
                return
            else:
                i += 1

# ──────────────────────────── форматирование ────────────────────────────

def fmt_amount(v):
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    if abs(v) >= 1:
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return (f"{v:.6f}".rstrip("0").rstrip(".")) or "0"

def fmt_assets(a):
    items = sorted(((k, v) for k, v in a.items() if v > 1e-12), key=lambda x: -x[1])
    return " + ".join(f"{fmt_amount(v)} {k}" for k, v in items[:3]) or "0"

def fmt_date(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y") if ts else "—"

def short(a, h=6, t=6):
    return a if len(a) <= h + t + 1 else f"{a[:h]}…{a[-t:]}"

# ──────────────────────────── адреса ────────────────────────────

RX_ETH = re.compile(r"0x[0-9a-fA-F]{40}")
RX_TON_RAW = re.compile(r"-?\d+:[0-9a-fA-F]{64}")
RX_TON_FR = re.compile(r"[A-Za-z0-9_+/=-]{48}")
RX_BTC = re.compile(r"bc1[02-9ac-hj-np-z]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}")

def detect_chain(a):
    a = a.strip()
    if RX_ETH.fullmatch(a):
        return "eth"
    if RX_TON_RAW.fullmatch(a) or RX_TON_FR.fullmatch(a):
        return "ton"
    if RX_BTC.fullmatch(a):
        return "btc"
    return None

def ton_to_raw(a):
    a = (a or "").strip()
    if RX_TON_RAW.fullmatch(a):
        wc, h = a.split(":", 1)
        return f"{wc}:{h.lower()}"
    if RX_TON_FR.fullmatch(a):
        try:
            raw = base64.urlsafe_b64decode(a.replace("+", "-").replace("/", "_") + "=" * (-len(a) % 4))
            wc = raw[1] - 256 if raw[1] > 127 else raw[1]
            return f"{wc}:{raw[2:34].hex()}"
        except Exception:
            pass
    return a.lower()

def _crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def ton_to_friendly(raw):
    if not RX_TON_RAW.fullmatch(raw):
        return raw
    wc, h = raw.split(":", 1)
    body = bytes([0x51, int(wc) & 0xFF]) + bytes.fromhex(h)   # 0x51 → "UQ…"
    return base64.urlsafe_b64encode(body + _crc16(body).to_bytes(2, "big")).decode()

def normalize(chain, a):
    a = a.strip()
    if chain == "eth":
        a = a.lower()
        return a if a.startswith("0x") else "0x" + a
    if chain == "ton":
        return ton_to_raw(a)
    return a

NAMES = {}      # адрес -> имя сервиса (из tonapi)
TYPED = {}      # адрес -> как пользователь его ввёл

def disp(a):
    return TYPED.get(a) or (ton_to_friendly(a) if RX_TON_RAW.fullmatch(a) else a)

# ──────────────────────────── сеть ────────────────────────────

class ApiError(Exception):
    pass

class RateLimiter:
    """Общий для всех потоков: не чаще одного запроса за interval секунд."""
    def __init__(self, interval):
        self.interval, self.next, self.lock = interval, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            t = max(time.time(), self.next)
            self.next = t + self.interval
        d = t - time.time()
        if d > 0:
            time.sleep(d)

UA = {"User-Agent": f"ChainTrace/{VERSION}"}

def http_json(url, limiter, headers=None, retries=5):
    last = "?"
    for i in range(retries):
        limiter.wait()
        try:
            req = urllib.request.Request(url, headers=headers or UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (400, 404):
                raise ApiError(last)
            time.sleep(1.5 * (2 ** i) if e.code in (402, 429) else 1.0)
        except Exception as e:
            last = str(e)
            time.sleep(1.0)
    raise ApiError(last)

def rec(frm, to, value, asset, ts, tx, uid):
    return {"frm": frm, "to": to, "value": value, "asset": asset, "ts": ts, "tx": tx, "uid": uid}

# ---- TON ----

def _norm_sym(s):
    s = (s or "").strip()
    return "USDT" if s.upper() in ("USDT", "USD₮") else (s or "JETTON")

def fetch_tonapi(addr, limit, key, lim):
    hdr = dict(UA)
    if key:
        hdr["Authorization"] = "Bearer " + key
    out, before, seen_events = [], None, 0
    while seen_events < limit:
        url = f"https://tonapi.io/v2/accounts/{urllib.parse.quote(addr)}/events?limit=100"
        if before:
            url += f"&before_lt={before}"
        data = http_json(url, lim, hdr)
        evs = data.get("events") or []
        if not evs:
            break
        seen_events += len(evs)
        for ev in evs:
            if ev.get("in_progress"):
                continue
            eid, ts = ev.get("event_id", ""), int(ev.get("timestamp") or 0)
            for i, act in enumerate(ev.get("actions") or []):
                typ = act.get("type")
                if typ not in ("TonTransfer", "JettonTransfer") or act.get("status") not in (None, "ok"):
                    continue                            # свопы и прочее — мимо
                t = act.get(typ) or {}
                s, r = t.get("sender") or {}, t.get("recipient") or {}
                f, to = ton_to_raw(s.get("address")), ton_to_raw(r.get("address"))
                for acc, a in ((s, f), (r, to)):
                    if acc.get("name") and a:
                        NAMES[a] = acc["name"]
                try:
                    if typ == "TonTransfer":
                        val, asset = int(t.get("amount") or 0) / 1e9, "TON"
                    else:
                        jet = t.get("jetton") or {}
                        val = int(t.get("amount") or 0) / 10 ** int(jet.get("decimals") or 9)
                        asset = _norm_sym(jet.get("symbol"))
                except (TypeError, ValueError):
                    continue
                if f and to and f != to and val > 0:
                    out.append(rec(f, to, val, asset, ts, f"{eid}:{i}", f"{eid}:{i}"))
        before = data.get("next_from")
        if not before or len(evs) < 100:
            break
    return out

def fetch_toncenter(addr, limit, lim):
    out, lt, h, n = [], None, None, 0
    while n < limit:
        url = (f"https://toncenter.com/api/v2/getTransactions?address={urllib.parse.quote(addr)}"
               f"&limit=100&archival=true")
        if lt and h:
            url += f"&lt={lt}&hash={urllib.parse.quote(h)}"
        rows = (http_json(url, lim) or {}).get("result") or []
        if lt:
            rows = rows[1:]                    # первая строка — повтор последней
        if not rows:
            break
        n += len(rows)
        for r in rows:
            tid = r.get("transaction_id") or {}
            lt, h = tid.get("lt"), tid.get("hash")
            msgs = [r.get("in_msg") or {}] + list(r.get("out_msgs") or [])
            for k, m in enumerate(msgs):
                f, to = ton_to_raw(m.get("source")), ton_to_raw(m.get("destination"))
                try:
                    val = int(m.get("value") or 0) / 1e9
                except ValueError:
                    continue
                if f and to and f != to and val > 0:
                    out.append(rec(f, to, val, "TON", int(r.get("utime") or 0), h, f"{h}:{k}"))
    return out

# ---- BTC ----

def fetch_mempool(addr, limit, lim):
    out, last, n = [], None, 0
    while n < limit:
        url = f"https://mempool.space/api/address/{addr}/txs"
        if last:
            url += f"/chain/{last}"
        rows = http_json(url, lim) or []
        rows = [t for t in rows if (t.get("status") or {}).get("confirmed")]
        if not rows:
            break
        n += len(rows)
        for t in rows:
            txid = t["txid"]
            ins = {(v.get("prevout") or {}).get("scriptpubkey_address") for v in t.get("vin") or []} - {None}
            ts = (t.get("status") or {}).get("block_time") or 0
            for oi, o in enumerate(t.get("vout") or []):
                oa = o.get("scriptpubkey_address")
                if not oa or oa in ins:          # сдача самому себе
                    continue
                for ia in ins:
                    out.append(rec(ia, oa, o.get("value", 0) / 1e8, "BTC", ts, txid, f"{txid}:{oi}:{ia}"))
        last = rows[-1]["txid"]
        if len(rows) < 25:
            break
    return out

# ---- ETH ----

def fetch_etherscan(addr, limit, key, lim):
    out = []
    for action in ("txlist", "tokentx"):
        url = ("https://api.etherscan.io/v2/api?chainid=1&module=account"
               f"&action={action}&address={addr}&page=1&offset={min(limit, 1000)}"
               f"&sort=desc&apikey={urllib.parse.quote(key)}")
        data = http_json(url, lim)
        if str(data.get("status")) == "0":
            if "No transactions" in str(data.get("message")):
                continue
            raise ApiError(str(data.get("result") or data.get("message")))
        for r in data.get("result") or []:
            try:
                if action == "txlist":
                    val, asset = int(r["value"]) / 1e18, "ETH"
                else:
                    val = int(r["value"]) / 10 ** int(r.get("tokenDecimal") or 18)
                    asset = r.get("tokenSymbol") or "TOKEN"
                f, to = r["from"].lower(), (r.get("to") or "").lower()
                if f and to and f != to and val > 0 and r.get("isError", "0") == "0":
                    out.append(rec(f, to, val, asset, int(r["timeStamp"]), r["hash"],
                                   f"{r['hash']}:{action}:{r.get('logIndex', '')}"))
            except (KeyError, ValueError):
                continue
    return out

def fetch_blockcypher(chain, addr, limit, token, lim):
    out, before, n = [], None, 0
    div = 1e8 if chain == "btc" else 1e18
    fix = (lambda a: "0x" + a.lower() if not a.startswith("0x") else a.lower()) if chain == "eth" else (lambda a: a)
    while n < limit:
        url = f"https://api.blockcypher.com/v1/{chain}/main/addrs/{addr}/full?limit=50"
        if before:
            url += f"&before={before}"
        if token:
            url += "&token=" + urllib.parse.quote(token)
        rows = http_json(url, lim).get("txs") or []
        if not rows:
            break
        n += len(rows)
        for t in rows:
            h = t.get("hash")
            ins = {fix(a) for i in t.get("inputs") or [] for a in i.get("addresses") or []}
            try:
                ts = int(datetime.fromisoformat(t.get("confirmed", t.get("received", "")).replace("Z", "+00:00")[:19]).replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                ts = 0
            for oi, o in enumerate(t.get("outputs") or []):
                for oa in o.get("addresses") or []:
                    oa = fix(oa)
                    if oa in ins:
                        continue
                    for ia in ins:
                        out.append(rec(ia, oa, o.get("value", 0) / div, SYM[chain], ts, h, f"{h}:{oi}:{ia}"))
        heights = [t.get("block_height") or 0 for t in rows]
        before = min(heights) if heights else None
        if len(rows) < 50 or not before:
            break
    return out

# ──────────────────────────── загрузчик (кэш + параллельно) ────────────────────────────

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".chaintrace_cache")

class Loader:
    def __init__(self, args, demo_map=None):
        self.a, self.demo = args, demo_map
        ch = args.chain
        interval = {"ton": 0.35 if args.ton_key else 1.1,
                    "eth": 0.22 if args.es_key else 0.4,
                    "btc": 0.35}[ch]
        self.lim = RateLimiter(interval)
        self.mem = {}
        self.errors = {}
        self.on_start = None

    def _cache_path(self, addr):
        h = hashlib.sha1(f"{self.a.chain}:{addr}:{self.a.limit}".encode()).hexdigest()[:20]
        return os.path.join(CACHE_DIR, h + ".json")

    def get(self, addr):
        if addr in self.mem:
            return self.mem[addr]
        if self.demo is not None:
            self.mem[addr] = self.demo.get(addr, [])
            return self.mem[addr]
        p = self._cache_path(addr)
        if self.a.cache and os.path.exists(p) and time.time() - os.path.getmtime(p) < self.a.cache_ttl:
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                NAMES.update(d.get("names", {}))
                self.mem[addr] = d["rows"]
                return d["rows"]
            except Exception:
                pass
        if self.on_start:
            self.on_start(addr)
        rows = self._fetch(addr)
        self.mem[addr] = rows
        if self.a.cache:
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                names = {k: NAMES[k] for r in rows for k in (r["frm"], r["to"]) if k in NAMES}
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({"rows": rows, "names": names}, f)
            except Exception:
                pass
        return rows

    def _fetch(self, addr):
        a, ch = self.a, self.a.chain
        if ch == "ton":
            try:
                rows = fetch_tonapi(addr, a.limit, a.ton_key, self.lim)
                if rows:
                    return rows
            except ApiError:
                pass
            return fetch_toncenter(addr, a.limit, self.lim)
        if ch == "eth":
            if a.es_key:
                try:
                    return fetch_etherscan(addr, a.limit, a.es_key, self.lim)
                except ApiError:
                    pass
            return fetch_blockcypher("eth", addr, a.limit, a.token, self.lim)
        try:
            return fetch_mempool(addr, a.limit, self.lim)
        except ApiError:
            return fetch_blockcypher("btc", addr, a.limit, a.token, self.lim)

    def get_many(self, addrs, cb=None):
        """Грузит много адресов параллельно, возвращает {addr: rows}."""
        res, done = {}, 0
        with ThreadPoolExecutor(max_workers=self.a.workers) as ex:
            futs = {ex.submit(self.get, x): x for x in addrs}
            for fu in as_completed(futs):
                x = futs[fu]
                done += 1
                try:
                    res[x] = fu.result()
                except Exception as e:
                    res[x] = []
                    self.errors[x] = str(e)
                if cb:
                    cb(done, len(addrs), x)
        return res

# ──────────────────────────── граф ────────────────────────────

class Graph:
    def __init__(self, cutoff=None):
        self.edges = defaultdict(dict)       # (u, v) -> {uid: rec}
        self.nb = defaultdict(set)
        self.cutoff = cutoff

    def feed(self, rows):
        for r in rows:
            if self.cutoff and r["ts"] and r["ts"] < self.cutoff:
                continue
            u, v = r["frm"], r["to"]
            if u != v:
                self.edges[(u, v)][r["uid"]] = r
                self.nb[u].add(v)
                self.nb[v].add(u)

    def one_way(self, u, v):
        recs = self.edges.get((u, v), {}).values()
        assets, txs, last = defaultdict(float), set(), 0
        for r in recs:
            assets[r["asset"]] += r["value"]
            txs.add(r["tx"])
            last = max(last, r["ts"])
        return len(txs), dict(assets), last

    def link(self, u, v):
        c1, a1, l1 = self.one_way(u, v)
        c2, a2, l2 = self.one_way(v, u)
        return {"fw": (c1, a1), "bw": (c2, a2), "cnt": c1 + c2,
                "vol": sum(a1.values()) + sum(a2.values()), "last": max(l1, l2)}

    def counterparties(self, x):
        """Контрагенты x, от самых частых к редким."""
        sc = {}
        for y in self.nb.get(x, ()):
            l = self.link(x, y)
            sc[y] = (l["cnt"], l["vol"])
        return sorted(sc, key=lambda y: (-sc[y][0], -sc[y][1]))

def is_hub(g, n, expanded):
    return n in NAMES or (n in expanded and len(g.nb.get(n, ())) >= HUB_DEGREE)

def find_paths(g, A, B, expanded, max_paths=300):
    """Все простые цепочки A → B длиной 1..4 звена."""
    NA, NB = g.nb.get(A, set()) - {B}, g.nb.get(B, set()) - {A}
    paths = []
    if B in g.nb.get(A, ()):
        paths.append([A, B])
    for m in NA & NB:
        paths.append([A, m, B])
    for m1 in NA:
        for m2 in (g.nb.get(m1, set()) & NB) - {A, B, m1}:
            paths.append([A, m1, m2, B])
    if len(paths) < max_paths:
        for m1 in NA:
            for m2 in g.nb.get(m1, set()) - {A, B}:
                for m3 in (g.nb.get(m2, set()) & NB) - {A, B, m1, m2}:
                    if m1 != m3:
                        paths.append([A, m1, m2, m3, B])
                        if len(paths) > 5000:
                            break

    def score(p):
        links = [g.link(p[i], p[i + 1]) for i in range(len(p) - 1)]
        hubs = sum(is_hub(g, n, expanded) for n in p[1:-1])
        return (hubs, -min(l["cnt"] for l in links), len(p), -sum(l["vol"] for l in links))
    paths.sort(key=score)
    return paths

# ──────────────────────────── рисование цепочек ────────────────────────────

class Labels:
    """Одинаковая метка узла во всех цепочках: Кошелёк 1/2, P1, P2…"""
    def __init__(self, A, B):
        self.m = {A: tr("w1")}
        self.A, self.B = A, B
        if B:
            self.m[B] = tr("w2")
        self.n = 0

    def __call__(self, x):
        if x not in self.m:
            self.n += 1
            self.m[x] = f"P{self.n}"
        return self.m[x]

    def short(self, x):
        if x == self.A:
            return tr("w1s")
        if x == self.B:
            return tr("w2s")
        return self(x)

def node_color(lbl):
    return cyan if lbl == tr("w1") else (green if lbl == tr("w2") else violet)

def edge_text(g, u, v):
    l = g.link(u, v)
    parts = []
    if l["fw"][0]:
        parts.append(green(f"{DOWN} {plural(l['fw'][0])} {DOT} {fmt_assets(l['fw'][1])}"))
    if l["bw"][0]:
        parts.append(yellow(f"{UP} {plural(l['bw'][0])} {DOT} {fmt_assets(l['bw'][1])}"))
    return "   ".join(parts) + gray(f"   {tr('last')} {fmt_date(l['last'])}")

def path_lines(g, path, lab, expanded):
    """Цепочка сверху вниз: узел, под ним переводы к следующему узлу."""
    out = []
    for i, n in enumerate(path):
        lbl = lab(n)
        corner = TOP if i == 0 else (BOT if i == len(path) - 1 else MID)
        extra = ""
        if n in NAMES:
            extra = gray(f"  [{NAMES[n]}]")
        elif is_hub(g, n, expanded):
            extra = gray("  " + tr("hub"))
        out.append(f"{gray(corner)} {bold(node_color(lbl)(f'{lbl:<11}'))}{disp(n)}{extra}")
        if i < len(path) - 1:
            out.append(f"{gray(V)}")
            out.append(f"{gray(V)}   {edge_text(g, n, path[i + 1])}")
            out.append(f"{gray(V)}")
    return out

def flow_list(g, A, direction, n=5):
    """Кто пополнял A (direction='in') или куда A отправлял ('out')."""
    rows = []
    for y in g.nb.get(A, ()):
        c, a, last = g.one_way(y, A) if direction == "in" else g.one_way(A, y)
        if c:
            rows.append((c, sum(a.values()), y, a, last))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    return rows[:n], len(rows)

def address_lines(lab, nodes):
    out = []
    for n in nodes:
        lbl = lab(n)
        nm = gray(f"  [{NAMES[n]}]") if n in NAMES else ""
        out.append(f"{bold(node_color(lbl)(f'{lbl:<11}'))}{disp(n)}{nm}")
    return out

# ──────────────────────────── HTML со схемами ────────────────────────────

def _mm(s):
    return str(s).replace('"', "'").replace("<", "‹").replace(">", "›")

def write_html(g, chain, items, lab, path_out, header):
    """items: список (заголовок, [узлы], [рёбра (u,v)])"""
    blocks, nodes_seen = [], {}
    for title, nodes, edges in items:
        lines = ["flowchart LR"]
        ids = {n: f"n{i}" for i, n in enumerate(nodes)}
        for n in nodes:
            lbl = lab(n)
            nodes_seen[n] = lbl
            sub = short(disp(n), 6, 6) + (f"<br/>{_mm(NAMES[n])}" if n in NAMES else "")
            lines.append(f'  {ids[n]}["<b>{_mm(lbl)}</b><br/>{_mm(sub)}"]')
            cls = "w1" if lbl == "Кошелёк 1" else ("w2" if lbl == "Кошелёк 2" else "mid")
            lines.append(f"  class {ids[n]} {cls}")
        for u, v in edges:
            for a, b in ((u, v), (v, u)):
                c, assets, _ = g.one_way(a, b)
                if c:
                    lines.append(f'  {ids[a]} -->|"{c}× · {_mm(fmt_assets(assets))}"| {ids[b]}')
        lines += ["  classDef w1 fill:#0e7490,color:#fff,stroke:#0e7490",
                  "  classDef w2 fill:#15803d,color:#fff,stroke:#15803d",
                  "  classDef mid fill:#f5f3ff,color:#3b0764,stroke:#7c3aed"]
        blocks.append(f"<section><h2>{html.escape(title)}</h2>"
                      f"<pre class='mermaid'>{html.escape(chr(10).join(lines))}</pre></section>")
    rows = "".join(
        f"<tr><td><b>{html.escape(l)}</b></td><td><a href='{EXPLORER[chain].format(disp(n))}' "
        f"target='_blank'>{html.escape(disp(n))}</a></td><td>{html.escape(NAMES.get(n, ''))}</td></tr>"
        for n, l in sorted(nodes_seen.items(), key=lambda kv: (kv[1][0] != "К", len(kv[1]), kv[1])))
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ChainTrace</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px;background:#fafafa;color:#111}}
section{{background:#fff;border:1px solid #e5e5e5;border-radius:10px;padding:12px 16px;margin:14px 0;overflow-x:auto}}
h1{{font-size:22px}} h2{{font-size:16px;margin:4px 0 8px}} .muted{{color:#666;font-size:14px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td{{border-top:1px solid #eee;padding:6px;word-break:break-all}}
a{{color:#0e7490}}
</style></head><body>
<h1>ChainTrace · {NAME[chain]}</h1><p class="muted">{html.escape(header)}<br>
Стрелка = направление денег, на ней — число переводов и сумма. Только прямые переводы (без свопов).</p>
{''.join(blocks)}
<section><h2>Адреса</h2><table>{rows}</table></section>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad:true,securityLevel:'loose',flowchart:{{htmlLabels:true}}}});</script>
</body></html>"""
    with open(path_out, "w", encoding="utf-8") as f:
        f.write(page)

# ──────────────────────────── демо ────────────────────────────

def build_demo(chain):
    def hx(s, n):
        return hashlib.sha256(("demo:" + s).encode()).hexdigest()[:n]
    names = ["A", "B", "X1", "X2", "X3", "X4", "EX"]
    if chain == "ton":
        N, M = {x: "0:" + hx(x, 64) for x in names}, 22.0
        NAMES[N["EX"]] = "Demo Exchange"
    elif chain == "btc":
        N, M = {x: "1" + hx(x, 33) for x in names}, 0.06
    else:
        N, M = {x: "0x" + hx(x, 40) for x in names}, 1.0
    E = [("X1", "A", .85, 1), ("A", "X1", .30, 2), ("X1", "A", .30, 3),
         ("A", "X2", .45, 2), ("X2", "A", .20, 6),
         ("X1", "X2", .75, 2), ("X1", "X2", .31, 5), ("X1", "X2", .52, 6), ("X2", "X1", .40, 7),
         ("X2", "B", .90, 3), ("B", "X2", .35, 6), ("X2", "B", .44, 7), ("B", "X2", .20, 8),
         ("X1", "X3", .50, 3), ("X3", "X4", 1.2, 4), ("X4", "B", 1.1, 5),
         ("A", "EX", 3.0, 1), ("EX", "B", 2.0, 2)]
    now = int(time.time())
    m = defaultdict(list)
    for i, (f, t, v, d) in enumerate(E):
        r = rec(N[f], N[t], v * M, SYM[chain], now - (10 - d) * 86400, f"demo{i}", f"demo{i}")
        m[N[f]].append(r)
        m[N[t]].append(r)
    return m, N["A"], N["B"]

# ──────────────────────────── главный сценарий ────────────────────────────

def run(args, A, B, ui, demo_map=None):
    """Грузит, ищет, рисует. Возвращает (страницы, итог) или None при ошибке."""
    t0 = time.time()
    ld = Loader(args, demo_map)
    ld.on_start = lambda x: ui.set_status(tr("loading", addr=disp(x)))
    cutoff = int(time.time()) - args.days * 86400 if args.days else None
    g = Graph(cutoff)

    mode = tr("last_days", d=args.days) if args.days else tr("all_history")
    ui.right = NAME[args.chain] + (f" {DOT} {tr('demo')}" if demo_map else "")
    ui.head = [cyan(f"{tr('w1'):<11}") + bold(disp(A))]
    if B:
        ui.head.append(green(f"{tr('w2'):<11}") + bold(disp(B)))
    ui.head.append(gray(f"{NAME[args.chain]} {DOT} {mode} {DOT} limit {args.limit} {DOT} expand {args.expand}"))
    ui.steps = [["active", tr("s_load"), ""], ["pending", tr("s_cp"), ""],
                ["pending", tr("s_find") if B else tr("s_links"), ""]]
    ui.notes, ui.foot = [], ""
    if not ui.live:
        print()
        for h in [bold(green(f"ChainTrace {VERSION}")) + gray(f"  {ui.right}")] + ui.head:
            print("  " + h)
        print()
    ui.busy(True)

    # 1 — истории двух кошельков
    base = ld.get_many([A] + ([B] if B else []))
    bad = [x for x in base if x in ld.errors]
    if bad:
        ui.step(0, "error")
        for x in bad:
            ui.note(red(tr("err_load", who=tr("w1") if x == A else tr("w2"), e=ld.errors[x])))
        ui.note(yellow(tr("hint_api")))
        ui.busy(False)
        return None
    for rows in base.values():
        g.feed(rows)
    na, nb = len(g.nb.get(A, ())), len(g.nb.get(B, ())) if B else 0
    ui.step(0, "done", tr("cp_count2", a=na, b=nb) if B else tr("cp_count", a=na))

    # 2 — самые частые контрагенты (сначала у кошелька с меньшим числом связей)
    first, second = (A, B)
    if B and nb < na:
        first, second = B, A
    ca = g.counterparties(first)
    cb = g.counterparties(second) if second else []
    order, seen = [], {A, B}
    for i in range(max(len(ca), len(cb))):
        for lst in (ca, cb):
            if i < len(lst) and lst[i] not in seen:
                seen.add(lst[i])
                order.append(lst[i])
    todo = order[:args.expand]
    ui.step(1, "active", bar(0, len(todo)))
    got = ld.get_many(todo, cb=lambda d, n, x: ui.step(1, "active", bar(d, n)))
    for rows in got.values():
        g.feed(rows)
    failed = sum(1 for x in todo if x in ld.errors)
    ui.step(1, "done", bar(len(todo), len(todo)))
    if failed:
        ui.note(yellow(tr("warn_failed", n=failed)))
    expanded = set(todo) | {A, B}
    lab = Labels(A, B)
    html_items, pages, shown = [], [], []

    # 3 — цепочки / связи
    ui.step(2, "active")
    summary = []
    if B:
        paths = find_paths(g, A, B, expanded)
        ui.step(2, "done", tr("found_n", n=len(paths)))
        if not paths:
            summary += [yellow(tr("no_chains")), gray(tr("no_chains_hint"))]
        else:
            top = paths[:args.show]
            summary += [bold(tr("found", n=len(paths))) + gray(f"  {DOT} {tr('showing', n=len(top))}"), ""]
            for k, p in enumerate(top, 1):
                weak = min(g.link(p[i], p[i + 1])["cnt"] for i in range(len(p) - 1))
                route = gray(f" {ARROW} ").join(node_color(lab(n))(lab.short(n)) for n in p)
                summary.append(f"{bold(violet(f'#{k}'))}  {steps_word(len(p) - 1):<8} {gray(DOT)} "
                               f"{tr('weakest', w=plural(weak)):<28}  {route}")
                title = f"{tr('chain_title', k=k)}  {DOT}  {steps_word(len(p) - 1)}  {DOT}  {tr('weakest', w=plural(weak))}"
                pages.append((title, [gray(tr("legend", d=DOWN, u=UP)), ""] + path_lines(g, p, lab, expanded)))
                html_items.append((title, p, list(zip(p, p[1:]))))
                shown += p
    else:
        for direction, key in (("in", "funded"), ("out", "sent")):
            rows, total = flow_list(g, A, direction)
            summary.append(bold(tr(key)) + gray(f"  {DOT} {tr('total', n=total)}"))
            if not rows:
                summary.append(gray("  " + tr("none")))
            for c, _, y, a, last in rows:
                nm = gray(f"  [{NAMES[y]}]") if y in NAMES else ""
                summary.append(f"  {violet(f'{lab(y):<4}')} {plural(c):<14} {fmt_assets(a):<20} "
                               f"{gray(fmt_date(last))}  {gray(short(disp(y), 8, 8))}{nm}")
                shown.append(y)
            summary.append("")
        cps = [x for x in todo if not is_hub(g, x, expanded)]
        pairs = []
        for i, x in enumerate(cps):
            for y in cps[i + 1:]:
                l = g.link(x, y)
                if l["cnt"]:
                    pairs.append((l["cnt"], l["vol"], x, y))
        pairs.sort(key=lambda r: (-r[0], -r[1]))
        ui.step(2, "done", tr("found_n", n=len(pairs)))
        if not pairs:
            summary.append(yellow(tr("no_links")))
        else:
            summary.append(bold(tr("links", n=len(pairs))))
            for k, (c, _, x, y) in enumerate(pairs[:args.show], 1):
                summary.append(f"  {bold(violet(f'#{k}'))}  {violet(lab(x))} {gray(DOWN + UP)} {violet(lab(y))}  {gray(DOT)} {plural(c)}")
                lines = [gray(tr("legend", d=DOWN, u=UP)), ""] + path_lines(g, [A, x, y], lab, expanded)
                if g.link(A, y)["cnt"]:
                    lines += ["", gray("+ " + tr("also", y=lab(y))), "  " + edge_text(g, A, y)]
                title = f"{tr('link_title', k=k)}  {DOT}  {lab(x)} {DOWN}{UP} {lab(y)}  {DOT}  {plural(c)}"
                pages.append((title, lines))
                html_items.append((title, [x, A, y], [(A, x), (x, y), (A, y)]))
                shown += [x, y]
    ui.busy(False)

    if html_items and not args.no_html:
        out = os.path.abspath(args.html)
        hdr = f"{tr('w1')}: {disp(A)}" + (f" · {tr('w2')}: {disp(B)}" if B else "")
        write_html(g, args.chain, html_items, lab, out, hdr)
        summary += ["", green(f"{OK} ") + gray(tr("html_saved", p=out))]
        if not args.no_open:
            try:
                webbrowser.open("file://" + out)
            except Exception:
                pass
    summary.append(gray(f"{OK} " + tr("done", t=f"{time.time() - t0:.1f}", n=len(ld.mem))))
    if ui.notes:
        summary += [""] + ui.notes

    nodes = list(dict.fromkeys([A] + ([B] if B else []) + shown))
    addr_page = address_lines(lab, nodes)
    pages = [(tr("summary"), summary)] + pages + [(tr("addresses"), addr_page)]
    return pages, summary + [""] + addr_page

# ──────────────────────────── запуск ────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="ChainTrace — chains of direct transfers BTC/ETH/TON")
    p.add_argument("wallet1", nargs="?")
    p.add_argument("wallet2", nargs="?")
    p.add_argument("--lang", choices=["ru", "en"], help="язык / language")
    p.add_argument("--chain", choices=["auto", "btc", "eth", "ton"], default="auto")
    p.add_argument("--limit", type=int, default=400, help="записей истории на кошелёк / history per wallet")
    p.add_argument("--expand", type=int, default=16, help="сколько контрагентов изучать / counterparties to load")
    p.add_argument("--days", type=int, default=0, help="только последние N дней, 0 = всё / last N days, 0 = all")
    p.add_argument("--show", type=int, default=5, help="сколько цепочек показать / chains to show")
    p.add_argument("--workers", type=int, default=4, help="параллельных загрузок / parallel downloads")
    p.add_argument("--html", default="chains.html")
    p.add_argument("--no-html", action="store_true")
    p.add_argument("--no-open", action="store_true", help="не открывать браузер / don't open browser")
    p.add_argument("--no-cache", dest="cache", action="store_false")
    p.add_argument("--cache-ttl", type=int, default=3600)
    p.add_argument("--token", default=os.environ.get("BLOCKCYPHER_TOKEN", ""))
    p.add_argument("--es-key", default=os.environ.get("ETHERSCAN_KEY", ""))
    p.add_argument("--ton-key", default=os.environ.get("TONAPI_KEY", ""))
    p.add_argument("--demo", action="store_true")
    return p.parse_args()

def choose_lang(ui, args):
    global LANG
    if args.lang:
        LANG = args.lang
        return
    if not ui.live:
        return
    ui.head, ui.steps, ui.right = [], None, ""
    ui.body = [bold("Язык  /  Language"), "",
               f"  {cyan('[1]')}  Русский",
               f"  {cyan('[2]')}  English"]
    ui.foot = "1 / 2"
    while True:
        c = ui.ask("").lower()
        if c in ("1", "ru", "р", ""):
            LANG = "ru"
            return
        if c in ("2", "en", "e", "англ"):
            LANG = "en"
            return
        if c in ("q", "й"):
            raise KeyboardInterrupt

def ask_wallets(ui, args):
    ui.head, ui.steps, ui.foot = [], None, ""
    ui.body = [gray(tr("start_hint")), gray(tr("start_hint2"))]
    w1 = ui.ask(tr("prompt_w1"))
    if w1.lower() == "demo":
        args.demo = True
        return
    args.wallet1 = w1
    ui.body += ["", cyan(f"{tr('w1'):<11}") + bold(w1)]
    args.wallet2 = ui.ask(tr("prompt_w2")) or None

def show_error(ui, msg):
    if ui.live:
        ui.steps, ui.foot = None, tr("exit")
        ui.body = [red(f"{ERR}  {msg}")]
        ui.ask("")
    else:
        print(red(f"  {ERR} {msg}"))

def main():
    _enable_ansi()
    args = parse_args()
    ui = UI()
    ui.open()
    final, code = None, 0
    try:
        choose_lang(ui, args)
        if not args.wallet1 and not args.demo:
            if not ui.live:
                print(tr("no_addr"))
                return 2
            ask_wallets(ui, args)
        if args.demo:
            args.chain = "ton" if args.chain == "auto" else args.chain
            m, A, B = build_demo(args.chain)
            res = run(args, A, B, ui, m)
        else:
            raws = [x.strip() for x in (args.wallet1, args.wallet2) if x and x.strip()]
            if not raws:
                show_error(ui, tr("no_addr"))
                return 2
            chains = {detect_chain(x) for x in raws}
            if args.chain == "auto":
                if None in chains or len(chains) > 1:
                    show_error(ui, tr("bad_net"))
                    return 2
                args.chain = chains.pop()
            addrs = [normalize(args.chain, x) for x in raws]
            for raw, a in zip(raws, addrs):
                TYPED[a] = raw if args.chain == "ton" else a
            if len(addrs) == 2 and addrs[0] == addrs[1]:
                show_error(ui, tr("same"))
                return 2
            res = run(args, addrs[0], addrs[1] if len(addrs) > 1 else None, ui)
        if res is None:
            code = 1
            if ui.live:
                ui.foot = tr("exit")
                ui.ask("")
        else:
            pages, final = res
            ui.pager(pages)
    except KeyboardInterrupt:
        code = 130
    finally:
        ui.close()
    # после выхода из окна оставляем в консоли короткий итог (его можно скопировать)
    if final and ui.live:
        print()
        print("  " + bold(green(tr("result_title"))) + gray(f"  {DOT} {ui.right}"))
        print()
        for l in final:
            print("  " + l)
        print()
    elif code == 130:
        print(yellow("  " + tr("interrupted")))
    return code

if __name__ == "__main__":
    sys.exit(main())
