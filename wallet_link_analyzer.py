#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================
  ChainTrace v1.0.0 (откройте консоль полностью) · by milyonok (откройте консоль полностью)
  Логика пользователя:
    1) СЕМЯ — кошелёк с МЕНЬШИМ числом транзакций.
    2) Смотрим ТОЛЬКО прямые переводы семени: кто его пополнил и
       кому он отправил. Обмены/свопы НЕ считаются (для TON берутся
       только действия TonTransfer/JettonTransfer, свопы отброшены).
    3) Подгружаем истории контрагентов и ищем, как ОНИ СВЯЗАНЫ МЕЖДУ
       СОБОЙ — в первую очередь по КОЛИЧЕСТВУ/ЧАСТОТЕ переводов,
       затем по СУММЕ. Дата в ранжировании не участвует.
    4) Выводим цепочку: кто пополнил семя -> кому семя отправил ->
       посредник1 <-> посредник2 (и где в паутине второй кошелёк).

  Запуск (библиотеки НЕ нужны, Python 3.8+):
    python wallet_link_analyzer.py                       <- окно-меню
    python wallet_link_analyzer.py UQDXVX…               <- семя явно
    python wallet_link_analyzer.py UQDXVX… UQCE…         <- семя+второй
    python wallet_link_analyzer.py --demo --chain ton
====================================================================
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone

VERSION = "1.0.0"
AUTHOR = "milyonok"
WIN_W = 100
LOG_KEEP = 16

CHAIN_SYM = {"btc": "BTC", "eth": "ETH", "ton": "TON"}
CHAIN_NAME = {"btc": "Bitcoin", "eth": "Ethereum", "ton": "The Open Network"}

# ----------------------------------------------------------------------
# Консоль / цвета / символы
# ----------------------------------------------------------------------

def _safe(ch, alt="?"):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        ch.encode(enc)
        return ch
    except Exception:
        return alt

CHK, CRS, WRN = _safe("✔", "+"), _safe("✘", "x"), _safe("⚠", "!")
ARR, DWN = _safe("→", "->"), _safe("▼", "v")
DBL = _safe("↔", "<->")
_BOX = _safe("═", "=") == "═"
T_H = "─" if _safe("─", "-") == "─" else "-"
T_V = "│" if _BOX else "|"
T_TL, T_TR = ("┌", "┐") if T_H == "─" else ("+", "+")
T_BL, T_BR = ("└", "┘") if T_H == "─" else ("+", "+")
T_ML, T_MR = ("├", "┤") if T_H == "─" else ("+", "+")

class C:
    R = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
    CYAN = "\033[96m"; VIO = "\033[95m"; GREEN = "\033[92m"
    RED = "\033[91m"; YEL = "\033[93m"; GRAY = "\033[90m"; WHITE = "\033[97m"

COLOR = True

def paint(text, *styles):
    if not COLOR or not styles:
        return str(text)
    return "".join(styles) + str(text) + C.R

_RX_ANSI = re.compile(r"\033\[[0-9;]*m")

def vw_len(s):
    return len(_RX_ANSI.sub("", str(s)))

def vtruncate(s, w):
    if vw_len(s) <= w:
        return s
    out, vis, i = [], 0, 0
    while i < len(s) and vis < max(w - 1, 1):
        m = _RX_ANSI.match(s, i)
        if m:
            out.append(m.group(0)); i = m.end(); continue
        out.append(s[i]); vis += 1; i += 1
    out.append("…")
    if COLOR:
        out.append(C.R)
    return "".join(out)

def enable_win_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        k.GetConsoleMode(h, ctypes.byref(mode))
        k.SetConsoleMode(h, mode.value | 0x4)
    except Exception:
        os.system("")

def clear_screen():
    if sys.stdout.isatty():
        sys.stdout.write("\033[H\033[2J")
        sys.stdout.flush()

def enter_alt():
    if sys.stdout.isatty():
        sys.stdout.write("\033[?1049h\033[H")
        sys.stdout.flush()

def leave_alt():
    if sys.stdout.isatty():
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()

# ----------------------------------------------------------------------
# Окно: перерисовывается целиком — спама в CMD нет
# ----------------------------------------------------------------------

def _fb(ch):
    return paint(ch, C.GRAY)

class Window:
    def __init__(self, right=""):
        self.right = right
        self.head, self.body = [], []
        self.progress = ""
        self.frozen = False
        self.rows = 0
        self.live = sys.stdout.isatty()
        self._t = 0.0

    def head_line(self, s=""):
        self.head.append(("l", s)); self.draw()

    def head_sep(self):
        self.head.append(("s", None)); self.draw()

    def add(self, s=""):
        self.body.append(("l", s)); self._trim(); self.draw()

    def sep(self):
        self.body.append(("s", None)); self._trim(); self.draw()

    def _trim(self):
        if not self.frozen and len(self.body) > LOG_KEEP:
            del self.body[: len(self.body) - LOG_KEEP]

    def set_progress(self, text=""):
        self.progress = text
        self.draw(force=True)

    def begin_final(self):
        self.progress = ""
        self.body.clear()
        self.frozen = True

    def _row(self, text):
        inner = WIN_W - 2
        shown = text if vw_len(text) <= inner - 2 else vtruncate(text, inner - 2)
        pad = inner - 1 - vw_len(shown)
        sys.stdout.write(_fb(T_V) + " " + shown + " " * max(pad, 0) + _fb(T_V) + "\n")

    def _sep(self):
        sys.stdout.write(_fb(T_ML + T_H * (WIN_W - 2) + T_MR) + "\n")

    def _top(self):
        title = f"  ChainTrace v{VERSION} (seed-web) "
        rt = f" {self.right} " if self.right else ""
        ndash = WIN_W - 2 - len(title) - len(rt) - 1
        sys.stdout.write(
            _fb(T_TL + T_H)
            + paint("  ChainTrace", C.GREEN, C.B)
            + paint(f" v{VERSION} (seed-web) ", C.GRAY)
            + _fb(T_H * max(ndash, 2))
            + paint(rt, C.GRAY) + _fb(T_TR) + "\n")

    def _bottom(self):
        sys.stdout.write(_fb(T_BL + T_H * (WIN_W - 2) + T_BR) + "\n")

    def draw(self, force=False, final=False):
        if not self.live and not final:
            return
        now = time.time()
        if self.live and not force and not final and now - self._t < 0.05:
            return
        self._t = now
        if self.live:
            clear_screen()
        rows = 0
        self._top(); rows += 1
        for kind, val in self.head:
            self._sep() if kind == "s" else self._row(val); rows += 1
        if self.head and self.body:
            self._sep(); rows += 1
        for kind, val in self.body:
            self._sep() if kind == "s" else self._row(val); rows += 1
        if self.progress:
            self._row(self.progress); rows += 1
        self._bottom(); rows += 1
        if self.live and rows < self.rows:
            for _ in range(self.rows - rows):
                sys.stdout.write(" " * WIN_W + "\n")
            sys.stdout.write(f"\033[{self.rows - rows}A")
        self.rows = rows
        sys.stdout.flush()

    def finish(self):
        self.progress = ""
        self.frozen = True
        self.draw(final=True)

WIN = None

def wline(text=""):
    if WIN is not None:
        WIN.add(text)
    else:
        inner = WIN_W - 2
        shown = text if vw_len(text) <= inner - 2 else vtruncate(text, inner - 2)
        pad = inner - 1 - vw_len(shown)
        print(_fb(T_V) + " " + shown + " " * max(pad, 0) + _fb(T_V))

def wsep():
    if WIN is not None:
        WIN.sep()
    else:
        print(_fb(T_ML + T_H * (WIN_W - 2) + T_MR))

def section(title):
    wline("")
    wline(paint(" ─── " + title + " ", C.B, C.CYAN) + paint(T_H * 10, C.GRAY))

def prog(msg, color=C.GRAY):
    if WIN is not None and not WIN.frozen:
        WIN.set_progress(paint("    " + msg, color))

def step(msg):
    prog("‣ " + msg, C.WHITE)

def ok_prog(msg):
    prog(CHK + " " + msg, C.GRAY)

# ----------------------------------------------------------------------
# Форматирование
# ----------------------------------------------------------------------

def short_addr(a, head=8, tail=6):
    a = str(a)
    return a if len(a) <= head + tail + 2 else f"{a[:head]}…{a[-tail:]}"

def fmt_amount(v):
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    s = f"{v:.8f}".rstrip("0").rstrip(".")
    return s if s else "0"

def fmt_date(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M") if ts else "—"

def fmt_assets(assets):
    items = [(a, v) for a, v in (assets or {}).items() if v > 1e-12]
    if not items:
        return "0"
    items.sort(key=lambda x: -x[1])
    return " + ".join(f"{fmt_amount(v)} {a}" for a, v in items[:2])

def pl(n, forms):
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return forms[0]
    if 2 <= m10 <= 4 and (m100 < 12 or m100 > 14):
        return forms[1]
    return forms[2]

TX_W = ("перевод", "перевода", "переводов")

# ----------------------------------------------------------------------
# Адреса: автодетект сети + TON raw <-> friendly
# ----------------------------------------------------------------------

RX_ETH = re.compile(r"0x[0-9a-fA-F]{40}")
RX_TON_RAW = re.compile(r"-?\d+:[0-9a-fA-F]{64}")
RX_TON_FRIENDLY = re.compile(r"[A-Za-z0-9_-]{48}")
RX_BTC = re.compile(r"(bc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})")

def full(rx, s):
    return bool(rx.fullmatch(s))

def detect_chain(addr):
    a = addr.strip()
    if full(RX_ETH, a):
        return "eth"
    if full(RX_TON_RAW, a) or full(RX_TON_FRIENDLY, a):
        return "ton"
    if full(RX_BTC, a):
        return "btc"
    return None

def ton_to_raw(addr):
    a = addr.strip()
    if full(RX_TON_RAW, a):
        wc, h = a.split(":", 1)
        return wc + ":" + h.lower()
    if not full(RX_TON_FRIENDLY, a):
        return a
    try:
        raw = base64.urlsafe_b64decode(a + "=" * (-len(a) % 4))
        if len(raw) < 34:
            return a
        wc = raw[1] - 256 if raw[1] > 127 else raw[1]
        return f"{wc}:{raw[2:34].hex()}"
    except Exception:
        return a

def _crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def ton_to_friendly(addr, bounceable=False):
    """Сырой TON-адрес '0:hex' -> кошельковый формат UQ… (тег 0x51; EQ… — 0x11)."""
    a = addr.strip()
    if not full(RX_TON_RAW, a):
        return a
    try:
        wc_s, h = a.split(":", 1)
        tag = 0x11 if bounceable else 0x51      # 0x51 => адрес начинается с "UQ…"
        body = bytes([tag, int(wc_s) & 0xFF]) + bytes.fromhex(h)
        return base64.urlsafe_b64encode(body + _crc16(body).to_bytes(2, "big")).decode().rstrip("=")
    except Exception:
        return a


def normalize(chain, addr):
    if chain == "eth":
        return addr.strip().lower()
    if chain == "ton":
        return ton_to_raw(addr)
    return addr.strip()

DISP, NAMES = {}, {}

def register_disp(raw, typed):
    if typed:
        DISP[raw] = typed.strip()

def show_addr(addr):
    """Показ адреса ТОЛЬКО в user-friendly формате (UQ…/EQ…); имена — в скобках."""
    base = DISP.get(addr)
    if base is None:
        base = ton_to_friendly(addr) if full(RX_TON_RAW, addr) else addr
    name = NAMES.get(addr)
    return f"{base} ({name})" if name else base

# ----------------------------------------------------------------------
# Спиннер
# ----------------------------------------------------------------------

class Spinner:
    FRAMES = "|/-\\"

    def __init__(self, text):
        self.text = text
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        i = 0
        while not self._stop.is_set():
            prog(self.FRAMES[i % 4] + " " + self.text, C.CYAN)
            i += 1
            time.sleep(0.12)

    def __enter__(self):
        if sys.stdout.isatty() and WIN is not None:
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=0.4)
        return False

# ----------------------------------------------------------------------
# HTTP + источники
# ----------------------------------------------------------------------

UA = {"User-Agent": f"ChainTrace/{VERSION}"}

class ApiFailure(Exception):
    pass

def http_json(url, retries=4, base_sleep=1.6, headers=None):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (402, 429):
                wait = base_sleep * (2 ** i)
                prog(f"{WRN} лимит API: жду {int(wait)}с ({i+1}/{retries})", C.YEL)
                time.sleep(wait)
                continue
            if e.code == 404:
                raise ApiFailure("404 not found")
            time.sleep(base_sleep)
        except Exception as e:
            last = str(e)
            time.sleep(base_sleep)
    raise ApiFailure(last or "unknown error")

def fetch_blockcypher(chain, address, limit, token):
    txs, seen, before = [], set(), None
    div = 1e8 if chain == "btc" else 1e18
    low = (chain == "eth")
    while len(txs) < limit:
        page = min(50, limit - len(txs))
        url = f"https://api.blockcypher.com/v1/{chain}/main/addrs/{address}/full?limit={page}"
        if before:
            url += f"&before={before}"
        if token:
            url += "&token=" + urllib.parse.quote(token)
        data = http_json(url)
        rows = data.get("txs") or []
        if not rows:
            break
        lowest = None
        for t in rows:
            h = t.get("hash")
            if not h or h in seen:
                continue
            seen.add(h)
            frm = [a.lower() if low else a for i in (t.get("inputs") or []) for a in (i.get("addresses") or [])]
            to = [a.lower() if low else a for o in (t.get("outputs") or []) for a in (o.get("addresses") or [])]
            val = sum(o.get("value", 0) for o in (t.get("outputs") or [])) / div
            try:
                ts = int(datetime.fromisoformat((t.get("received") or "").replace("Z", "+00:00")).timestamp())
            except Exception:
                ts = 0
            txs.append({"hash": h, "ts": ts, "frm": frm, "to": to, "value": val,
                        "asset": CHAIN_SYM[chain]})
            bh = t.get("block_height") or 0
            lowest = bh if lowest is None else min(lowest, bh)
        if lowest is None or len(rows) < page:
            break
        before = lowest
    return txs

def fetch_etherscan(address, limit, api_key):
    offset = min(limit, 1000)
    url = ("https://api.etherscan.io/v2/api?chainid=1&module=account&action=txlist"
           f"&address={address}&startblock=0&endblock=99999999&page=1&offset={offset}"
           f"&sort=desc&apikey={urllib.parse.quote(api_key)}")
    data = http_json(url)
    if str(data.get("status")) == "0":
        if "No transactions" in str(data.get("message", "")):
            return []
        raise ApiFailure(str(data.get("result") or data.get("message") or "etherscan error"))
    out = []
    for r in data.get("result") or []:
        try:
            out.append({"hash": r["hash"], "ts": int(r.get("timeStamp", 0)),
                        "frm": [r["from"].lower()], "to": [r["to"].lower()] if r.get("to") else [],
                        "value": int(r.get("value", 0)) / 1e18, "asset": "ETH"})
        except Exception:
            continue
    return out

def _norm_asset(sym):
    s = (sym or "").strip()
    if s.upper() == "USDT" or s == "USD₮":
        return "USDT"
    if s.upper() == "USDC":
        return "USDC"
    return s or "JETTON"

def fetch_tonapi(address, limit, api_key):
    """События TON: ТОЛЬКО прямые переводы TonTransfer/JettonTransfer.
    Свопы, деплои контрактов и прочие действия сюда НЕ попадают — это и есть
    фильтр 'не обмены, а только прямые переводы'."""
    headers = dict(UA)
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    out, seen, before_lt = [], set(), None
    while len(out) < limit:
        page = min(100, limit - len(out))
        url = f"https://tonapi.io/v2/accounts/{urllib.parse.quote(address)}/events?limit={page}"
        if before_lt:
            url += f"&before_lt={before_lt}"
        data = http_json(url, headers=headers)
        events = data.get("events") or []
        if not events:
            break
        nxt = data.get("next_from")
        for ev in events:
            if ev.get("in_progress"):
                continue
            ev_id = ev.get("event_id") or ""
            for idx, act in enumerate(ev.get("actions") or []):
                if act.get("status") not in (None, "ok"):
                    continue
                typ = act.get("type")
                if typ == "TonTransfer":
                    t = act.get("TonTransfer") or {}
                    snd = t.get("sender") or {}
                    rcp = t.get("recipient") or {}
                    f = (snd.get("address") or "").lower()
                    to = (rcp.get("address") or "").lower()
                    val = float(t.get("amount") or 0) / 1e9
                    asset = "TON"
                    for acc in (snd, rcp):
                        nm = acc.get("name")
                        if nm and acc.get("address"):
                            NAMES[(acc["address"]).lower()] = nm
                elif typ == "JettonTransfer":
                    t = act.get("JettonTransfer") or {}
                    snd = t.get("sender") or {}
                    rcp = t.get("recipient") or {}
                    f = (snd.get("address") or "").lower()
                    to = (rcp.get("address") or "").lower()
                    jet = t.get("jetton") or {}
                    try:
                        dec = int(jet.get("decimals") or 6)
                    except Exception:
                        dec = 6
                    val = float(t.get("amount") or 0) / (10 ** dec)
                    asset = _norm_asset(jet.get("symbol"))
                    for acc in (snd, rcp):
                        nm = acc.get("name")
                        if nm and acc.get("address"):
                            NAMES[(acc["address"]).lower()] = nm
                else:
                    continue        # JettonSwap, ContractDeploy и т.п. — мимо
                if not f or not to or f == to or val <= 0:
                    continue
                h = f"{ev_id}:{idx}"
                if h not in seen:
                    seen.add(h)
                    out.append({"hash": h, "ts": int(ev.get("timestamp") or 0),
                                "frm": [f], "to": [to], "value": val, "asset": asset})
        if not nxt or len(events) < page:
            break
        before_lt = nxt
        time.sleep(0.35)
    return out

def fetch_toncenter(address, limit):
    out, seen = [], set()
    lt = txh = None
    while len(out) < limit:
        page = min(100, limit - len(out))
        url = ("https://toncenter.com/api/v2/getTransactions"
               f"?address={urllib.parse.quote(address)}&limit={page}&archival=true")
        if lt and txh:
            url += f"&lt={lt}&hash={urllib.parse.quote(str(txh))}"
        data = http_json(url)
        rows = (data or {}).get("result") or []
        if not rows:
            break
        for r in rows:
            tid = r.get("transaction_id") or {}
            lt, txh = tid.get("lt"), tid.get("hash")
            ts = int(r.get("utime") or 0)
            msgs = []
            im = r.get("in_msg") or {}
            if im.get("source") and im.get("destination"):
                msgs.append(im)
            msgs += [om for om in (r.get("out_msgs") or []) if om.get("source") and om.get("destination")]
            for k, m in enumerate(msgs):
                try:
                    val = int(m.get("value") or 0) / 1e9
                except Exception:
                    continue
                if val <= 0:
                    continue
                h = f"{txh or lt}:{k}"
                if h not in seen:
                    seen.add(h)
                    out.append({"hash": h, "ts": ts,
                                "frm": [str(m["source"]).lower()],
                                "to": [str(m["destination"]).lower()],
                                "value": val, "asset": "TON"})
        if len(rows) < page:
            break
        time.sleep(1.05)
    return out

# ----------------------------------------------------------------------
# Демо-данные (свежие даты)
# ----------------------------------------------------------------------

def _hx(name, n):
    return hashlib.sha256(("demo:" + name).encode()).hexdigest()[:n]

def build_demo(chain):
    names = ["A", "B", "X1", "X2", "X3", "X4"]
    if chain == "btc":
        N = {x: "1" + _hx(x, 33) for x in names}
        M = 0.06
    elif chain == "ton":
        N = {x: "0:" + _hx(x, 64) for x in names}
        M = 22.0
    else:
        N = {x: "0x" + _hx(x, 40) for x in names}
        M = 1.0
    # ГАРАНТИРОВАННАЯ цепочка для демо:
    #   Кошелёк 1 (главный) <-> X1 и X2;  X1 <-> X2 (самый частый стык);
    #   X2 <-> Кошелёк 2;  запасная ветка X1 -> X3 -> Кошелёк 2.
    edges = [
        ("X1", "A", 0.85 * M, 1), ("A", "X1", 0.30 * M, 2), ("X1", "A", 0.30 * M, 3),
        ("A", "X2", 0.45 * M, 2), ("X2", "A", 0.20 * M, 6),
        ("X1", "X2", 0.75 * M, 2), ("X1", "X2", 0.31 * M, 5),
        ("X1", "X2", 0.52 * M, 6), ("X2", "X1", 0.40 * M, 7),
        ("X2", "B", 0.90 * M, 3), ("B", "X2", 0.35 * M, 6),
        ("X2", "B", 0.44 * M, 7), ("B", "X2", 0.20 * M, 8),
        ("X1", "X3", 0.50 * M, 3), ("X3", "B", 2.10 * M, 4), ("X3", "B", 0.60 * M, 9),
    ]
    if chain == "ton":
        edges += [("X1", "X2", 1200.0, 4), ("X2", "B", 1500.0, 5)]  # USDT-переводы
    now = int(time.time())
    span = 60 * 86400
    max_day = max(d for *_e, d in edges)
    by_addr = defaultdict(list)
    for i, (f, t, v, day) in enumerate(edges):
        ts = now - span + int((day / max_day) * span) + i * 700
        tx = {"hash": "demo" + hashlib.sha256(f"{chain}:{i}:{f}{t}".encode()).hexdigest()[:56],
              "ts": ts, "frm": [N[f]], "to": [N[t]], "value": v,
              "asset": "USDT" if v >= 1000 else CHAIN_SYM[chain]}
        by_addr[N[f]].append(tx)
        by_addr[N[t]].append(tx)
    return by_addr, N["A"], N["B"]

# ----------------------------------------------------------------------
# Граф
# ----------------------------------------------------------------------

class WalletGraph:
    def __init__(self):
        self.adj = defaultdict(dict)

    def add_tx(self, tx):
        for f in tx["frm"]:
            for t in tx["to"]:
                if f != t:
                    self.adj[f].setdefault(t, {})[tx["hash"]] = tx

    def edge(self, u, v):
        return self.adj.get(u, {}).get(v, {})

def flow(g, u, v, chain):
    assets = {}
    e = g.edge(u, v)
    for t in e.values():
        a = t.get("asset") or CHAIN_SYM[chain]
        assets[a] = assets.get(a, 0.0) + t["value"]
    return len(e), assets

def flow_pair(g, u, v, chain):
    c1, a1 = flow(g, u, v, chain)
    c2, a2 = flow(g, v, u, chain)
    tot = dict(a1)
    for k, v in a2.items():
        tot[k] = tot.get(k, 0.0) + v
    return c1 + c2, tot

def vol_num(assets):
    return sum(assets.values())

def freshest(g, u, v):
    txs = list(g.edge(u, v).values()) + list(g.edge(v, u).values())
    return max(txs, key=lambda t: t["ts"]) if txs else None

def touches(g, u, v):
    return bool(g.edge(u, v) or g.edge(v, u))

class Fetcher:
    def __init__(self, args):
        self.args = args
        self.cache = {}
        self.expanded = 0
        self.last = 0.0
        self.demo_map = build_demo(args.chain)[0] if args.demo else None

    def txs(self, addr, is_seed=False):
        if addr in self.cache:
            return self.cache[addr]
        if self.demo_map is not None:
            data = list(self.demo_map.get(addr, []))
            self.cache[addr] = data
            return data
        if not is_seed:
            self.expanded += 1
        pause = self.args.sleep - (time.time() - self.last)
        if pause > 0:
            time.sleep(pause)
        self.last = time.time()
        with Spinner("гружу " + short_addr(show_addr(addr), 14, 10)):
            if self.args.chain == "ton":
                try:
                    data = fetch_tonapi(addr, self.args.limit, self.args.ton_key)
                except ApiFailure:
                    data = []
                if not data:
                    try:
                        data = fetch_toncenter(addr, self.args.limit)
                    except ApiFailure:
                        data = []
            elif self.args.chain == "eth" and self.args.es_key:
                try:
                    data = fetch_etherscan(addr, self.args.limit, self.args.es_key)
                except ApiFailure:
                    data = fetch_blockcypher("eth", addr, self.args.limit, self.args.token)
            else:
                data = fetch_blockcypher(self.args.chain, addr, self.args.limit, self.args.token)
        self.cache[addr] = data
        return data

# ----------------------------------------------------------------------
# АНАЛИЗ ПО ЛОГИКЕ ПОЛЬЗОВАТЕЛЯ: семя -> его прямые переводы -> стыки
# ----------------------------------------------------------------------

def analyze_web(fetcher, a, b, args, cutoff=None):
    ch = args.chain
    g = WalletGraph()
    skipped_old = 0

    def in_window(t):
        return not cutoff or not t.get("ts") or t["ts"] >= cutoff

    def feed(rows):
        nonlocal skipped_old
        kept = 0
        for t in rows:
            if not in_window(t):
                skipped_old += 1
                continue
            g.add_tx(t)
            kept += 1
        return kept

    # ── 1. истории; СЕМЯ — кошелёк с МЕНЬШИМ числом транзакций ─────────
    step("[1/3] Истории кошельков · главный — у кого меньше переводов")
    raw_a = fetcher.txs(a, is_seed=True)
    raw_b = fetcher.txs(b, is_seed=True) if b else []
    ca = sum(1 for t in raw_a if in_window(t))
    cb = sum(1 for t in raw_b if in_window(t)) if b else 10 ** 12
    if b and cb < ca:
        seed, buddy, seed_role, buddy_role = b, a, "Кошелёк 2", "Кошелёк 1"
        cn_seed, cn_buddy = cb, ca
    else:
        seed, buddy, seed_role, buddy_role = a, b, "Кошелёк 1", "Кошелёк 2"
        cn_seed, cn_buddy = ca, cb
    if b:
        ok_prog(f"основной = {seed_role}: {cn_seed} tx в окне (у {buddy_role}: {cn_buddy})")
    else:
        ok_prog(f"основной = {seed_role}: {cn_seed} tx в окне")
    kept_seed = feed(raw_a if seed == a else raw_b)
    kept_buddy = feed(raw_b if seed == a else raw_a) if b else 0

    # ── 2. контрагенты семени по ПРЯМЫМ переводам ──────────────────────
    step("[2/3] Пополнения и отправки основного кошелька (только переводы, без обменов)")
    stats = {}
    for x in g.adj.get(seed, {}):
        stats.setdefault(x, None)
    for src, dsts in g.adj.items():
        if seed in dsts:
            stats.setdefault(src, None)
    stats.pop(seed, None)
    if buddy:
        stats.pop(buddy, None)
    cp_stats = {}
    for x in stats:
        cin, ain = flow(g, x, seed, ch)     # x  -> seed  (нас пополнили)
        cout, aout = flow(g, seed, x, ch)   # seed -> x  (мы отправили)
        fr_t = freshest(g, x, seed)
        cp_stats[x] = {"inc": cin, "inc_assets": ain, "out": cout, "out_assets": aout,
                       "total": cin + cout, "vol": vol_num(ain) + vol_num(aout),
                       "last": fr_t["ts"] if fr_t else 0}
    rank = sorted(cp_stats, key=lambda x: (-cp_stats[x]["total"], -cp_stats[x]["vol"]))
    ok_prog(f"контрагентов у основного кошелька: {len(rank)}")

    # — подгружаем истории контрагентов (бюджет), предпочтение — частым —
    opened = []
    capped = False
    for m in rank:
        if fetcher.expanded >= args.expand:
            capped = True
            break
        try:
            feed(fetcher.txs(m, is_seed=False))
            opened.append(m)
            prog(f"{CHK} контрагент #{len(opened)}  {short_addr(show_addr(m), 16, 10)}", C.GRAY)
        except ApiFailure:
            continue

    # ── 3. стыки контрагентов МЕЖДУ СОБОЙ: частота -> сумма ────────────
    step("[3/3] Стыки контрагентов между собой (сначала самые частые)")
    pairs = []
    for i, x in enumerate(opened):
        for y in opened[i + 1:]:
            cnt, assets = flow_pair(g, x, y, ch)
            if cnt:
                pairs.append((cnt, vol_num(assets), x, y, assets))
    pairs.sort(key=lambda v: (-v[0], -v[1]))
    ok_prog(f"связок найдено: {len(pairs)}")

    # — где в паутине второй кошелёк —
    buddy_links = []
    if buddy:
        nodes_all = set(rank) | set(opened) | {seed}
        for n in g.adj.get(buddy, {}):
            nodes_all.add(n)
        for src, dsts in g.adj.items():
            if buddy in dsts:
                nodes_all.add(src)
        for n in nodes_all:
            if n in (buddy,):
                continue
            cnt, assets = flow_pair(g, buddy, n, ch)
            if cnt:
                buddy_links.append((cnt, vol_num(assets), n, assets))
        buddy_links.sort(key=lambda v: (-v[0], -v[1]))

    return {"graph": g, "seed": seed, "buddy": buddy, "wa": a, "wb": b,
            "seed_role": seed_role, "buddy_role": buddy_role,
            "cp": cp_stats, "rank": rank, "opened": opened, "pairs": pairs,
            "buddy_links": buddy_links, "capped": capped,
            "skipped_old": skipped_old, "expanded": fetcher.expanded,
            "kept_seed": kept_seed, "kept_buddy": kept_buddy}

# ----------------------------------------------------------------------
# Отображение
# ----------------------------------------------------------------------

def role_color(node, res):
    if node == res["seed"]:
        return C.YEL
    if node == res.get("buddy"):
        return C.GREEN
    return C.WHITE

def web_body(res, args):
    ch = args.chain
    seed, buddy = res["seed"], res.get("buddy")
    cp, pairs = res["cp"], res["pairs"]
    g = res["graph"]

    # ДВА ГЛАВНЫХ ПОСРЕДНИКА (верхняя связка) — их помечаем везде как ★1 и ★2
    X1, X2 = (pairs[0][2], pairs[0][3]) if pairs else (None, None)

    def star(n):
        if X1 and n == X1:
            return paint("  ★1", C.VIO, C.B)
        if X2 and n == X2:
            return paint("  ★2", C.VIO, C.B)
        return ""

    def addr_line(n, color=C.WHITE, indent=6):
        """Адрес ПОЛНОСТЬЮ + имя сервиса на следующей строке (если есть)."""
        base = DISP.get(n) or (ton_to_friendly(n) if full(RX_TON_RAW, n) else n)
        wline(" " * indent + paint(base, color, C.B))
        nm = NAMES.get(n)
        if nm:
            wline(" " * indent + paint(f"↳ {nm}", C.GRAY))

    def short_uq(n, head=6, tail=4):
        """Короткий вид адреса СТРОГО в UQ…-формате (для однострочных мест)."""
        base = DISP.get(n) or (ton_to_friendly(n) if full(RX_TON_RAW, n) else n)
        return short_addr(base, head, tail)

    wsep()
    living = [x for x in res["rank"] if cp[x]["total"] > 0]
    wline("   " + paint(CHK, C.GREEN, C.B) + "  "
          + paint(f"ПАУТИНА · {res['seed_role']}: {len(living)} {pl(len(living), ('контрагент', 'контрагента', 'контрагентов'))}", C.GREEN, C.B)
          + paint(f"   · связок между ними: {len(pairs)}", C.GRAY))
    if res["skipped_old"]:
        wline("      " + paint(f"за окном ({args.days} дн) отброшено старых переводов: {res['skipped_old']}", C.GRAY))
    if res["capped"]:
        wline("      " + paint(f"{WRN} бюджет контрагентов исчерпан ({res['expanded']}) — глубже: --expand", C.YEL))

    ins = [x for x in res["rank"] if cp[x]["inc"] > 0]
    outs = [x for x in res["rank"] if cp[x]["out"] > 0]

    # ── пополнения основного кошелька ──
    section(f"КТО ПОПОЛНЯЛ · {res['seed_role']}")
    if ins:
        for i, x in enumerate(ins[:6], 1):
            wline(paint(f"   {i}.", C.VIO, C.B) + star(x))
            addr_line(x)
            wline(paint(f"      {cp[x]['inc']} {pl(cp[x]['inc'], TX_W)} · {fmt_assets(cp[x]['inc_assets'])}"
                        f" · {fmt_date(cp[x]['last'])[:10]}", C.CYAN))
        if len(ins) > 6:
            wline(paint(f"      … и ещё {len(ins) - 6}", C.GRAY))
    else:
        wline("      " + paint("пополнений в окне нет", C.GRAY))

    # ── отправки основного кошелька ──
    section(f"КУДА ОТПРАВЛЯЛ · {res['seed_role']}")
    if outs:
        for i, x in enumerate(outs[:6], 1):
            wline(paint(f"   {i}.", C.VIO, C.B) + star(x))
            addr_line(x)
            wline(paint(f"      {cp[x]['out']} {pl(cp[x]['out'], TX_W)} · {fmt_assets(cp[x]['out_assets'])}"
                        f" · {fmt_date(cp[x]['last'])[:10]}", C.YEL))
        if len(outs) > 6:
            wline(paint(f"      … и ещё {len(outs) - 6}", C.GRAY))
    else:
        wline("      " + paint("отправок в окне нет", C.GRAY))

    # ── ГЛАВНОЕ: связь между двумя посредниками (крупная схема) ──
    section("СВЯЗЬ МЕЖДУ ПОСРЕДНИКАМИ 1 И 2")
    if pairs:
        cnt, vol, x, y, assets = pairs[0]
        fresh = freshest(g, x, y)
        c_xy = flow(g, x, y, ch)[0]
        c_yx = flow(g, y, x, ch)[0]
        arrow = f"{short_addr(x, 6, 4)} {ARR} {short_addr(y, 6, 4)}" if c_xy >= c_yx else f"{short_addr(y, 6, 4)} {ARR} {short_addr(x, 6, 4)}"

        wline("   " + paint("★ ПОСРЕДНИК 1", C.VIO, C.B))
        addr_line(x, C.VIO, 6)
        wline("        " + paint(T_V, C.GRAY))
        wline("        " + paint(T_V, C.GRAY) + paint(f"   {cnt} {pl(cnt, TX_W)} · {fmt_assets(assets)}", C.YEL, C.B))
        wline("        " + paint(T_V, C.GRAY) + paint(f"   направление: {arrow}", C.GRAY))
        wline("        " + paint(DWN, C.YEL, C.B))
        wline("   " + paint("★ ПОСРЕДНИК 2", C.VIO, C.B))
        addr_line(y, C.VIO, 6)
        wline("")
        wline("   " + paint("★ ЭТИ ДВА КОШЕЛЬКА ПЕРЕВОДИЛИ ДРУГ ДРУГУ", C.GREEN, C.B)
              + paint(f"  ·  {cnt} {pl(cnt, TX_W)} · {fmt_assets(assets)}"
                      + (f" · посл. {fmt_date(fresh['ts'])[:10]}" if fresh else ""), C.GRAY))
        # остальные связки — коротко
        if len(pairs) > 1:
            wline("")
            wline("      " + paint("другие связки в паутине:", C.GRAY))
            for i, (c2, v2, a2, b2, as2) in enumerate(pairs[1:6], 2):
                wline(paint(f"        {i}. ", C.VIO) + paint(f"{short_addr(a2, 10, 6)} {DBL} {short_addr(b2, 10, 6)}", C.WHITE)
                      + paint(f"  ·  {c2} {pl(c2, TX_W)} · {fmt_assets(as2)}", C.GRAY))
    else:
        wline("      " + paint("прямых переводов между посредниками не найдено", C.YEL, C.B))

    # ── второй кошелёк: только нити к посредникам СВЯЗКИ (без посторонних адресов) ──
    sr, br = res["seed_role"], res["buddy_role"]
    if buddy and pairs:
        bl = res["buddy_links"]
        key = [it for it in bl if it[2] in (X1, X2)]
        if key:
            section("КАК КОШЕЛЁК 2 СВЯЗАН С ПОСРЕДНИКАМИ ИЗ СВЯЗКИ")
            for cnt, vol, n, assets in key:
                role_txt = "ПОСРЕДНИК 2 (★2)" if n == X2 else "ПОСРЕДНИК 1 (★1)"
                wline("   " + paint(f"{br} {DBL} {role_txt}", C.GREEN, C.B))
                addr_line(n)
                wline(paint(f"      {cnt} {pl(cnt, TX_W)} · {fmt_assets(assets)}", C.CYAN))
        else:
            section("КАК КОШЕЛЁК 2 СВЯЗАН С ПОСРЕДНИКАМИ ИЗ СВЯЗКИ")
            wline("      " + paint("нить к связке идёт глубже — в пределах историй не видно", C.GRAY))

    # ── итог: развёрнутая цепь ──
    wline("")
    wsep()
    if pairs:
        cnt, vol, x, y, assets = pairs[0]
        wline("   " + paint("ИТОГ · ЦЕПЬ ЦЕЛИКОМ:", C.GREEN, C.B))
        # цепь собираем только из нитей, которые РЕАЛЬНО найдены
        bh_y = any(it[2] == y for it in res["buddy_links"]) if buddy else False
        bh_x = any(it[2] == x for it in res["buddy_links"]) if buddy else False
        if bh_y:
            chain_txt = f"{br} {ARR} {short_uq(y, 6, 6)} {ARR} {short_uq(x, 6, 6)} {ARR} {sr}"
            legend = f"(то есть: {br} → посредник 2 → посредник 1 → {sr})"
        elif bh_x:
            chain_txt = f"{br} {ARR} {short_uq(x, 6, 6)} {ARR} {short_uq(y, 6, 6)} {ARR} {sr}"
            legend = f"(то есть: {br} → посредник 1 → посредник 2 → {sr})"
        else:
            chain_txt = f"{sr} {DBL} {short_uq(x, 6, 6)} {DBL} {short_uq(y, 6, 6)}"
            legend = "(два посредника основного кошелька связаны между собой)"
        wline("      " + paint(chain_txt, C.WHITE, C.B))
        wline("      " + paint(legend, C.GRAY))
        wline("      " + paint(f"★ посредники 1 и 2 связаны между собой: {cnt} {pl(cnt, TX_W)} · {fmt_assets(assets)}", C.GREEN, C.B))
        wline("      " + paint("полные адреса, направления и даты — на следующем экране (нажмите Enter)", C.GRAY))
    else:
        wline("   " + paint("ИТОГ: связок между посредниками не найдено в пределах историй.", C.YEL, C.B))

def chain_screen(res, pair, args, title):
    """Линейная цепочка ОТ Кошелька 1 ДО Кошелька 2 по реальным рёбрам."""
    global WIN
    if not pair:
        return
    ch = args.chain
    g = res["graph"]
    cnt, vol, x, y, assets = pair
    seed, buddy = res["seed"], res.get("buddy")
    wa, wb = res.get("wa"), res.get("wb")

    role = {}
    if wa:
        role[wa] = "Кошелёк 1"
    if wb:
        role[wb] = "Кошелёк 2"
    mid_idx = {n: i for i, n in enumerate(dict.fromkeys([x, y]), 1)}

    def label(n):
        return role.get(n) or f"посредник {mid_idx.get(n, '?')}"

    def color(n):
        return C.CYAN if n == wa else (C.GREEN if n == wb else C.VIO)

    # РАСКЛАДКА ЦЕПОЧКИ: главная задача — показать связь ДВУХ посредников.
    # Поэтому ребро x <-> y ОБЯЗАТЕЛЬНО должно быть звеном цепочки:
    #   Кошелёк 1 ... посредник 1 <-> посредник 2 ... Кошелёк 2
    start_n = wa if wa else x
    end_n = wb if wb else y
    pool = list(dict.fromkeys(n for n in [wa, wb, seed, buddy, x, y] if n))

    def gap_bridge(w, v, used):
        for m in pool:
            if m in used or m == v:
                continue
            if touches(g, w, m) and touches(g, m, v):
                return m
        return None

    def walk_order(seq):
        chain = [seq[0]]
        for nxt in seq[1:]:
            last = chain[-1]
            if touches(g, last, nxt):
                chain.append(nxt)
                continue
            m = gap_bridge(last, nxt, set(chain) | {nxt})
            if m is None:
                return None
            chain += [m, nxt]
        return chain

    cands = []
    for p, q in ((x, y), (y, x)):
        seq = [start_n] + [u for u in (p, q, end_n) if u != start_n]
        chn = walk_order(seq)
        if chn and p in chn and q in chn and abs(chn.index(p) - chn.index(q)) == 1:
            score = sum(flow_pair(g, chn[i], chn[i + 1], ch)[0] for i in range(len(chn) - 1))
            cands.append((score, chn))
    if cands:
        path = max(cands, key=lambda z: z[0])[1]
        inline_xy = True
    else:
        # запасной вариант: обычный обход, а стык покажем отдельным блоком ниже
        inline_xy = False
        best = {"path": [start_n], "score": -1}

        def dfs(node, path_nodes, total):
            for nxt in pool:
                if nxt in path_nodes or not touches(g, node, nxt):
                    continue
                path2 = path_nodes + [nxt]
                c2, _ = flow_pair(g, node, nxt, ch)
                score = total + c2 * 10 + (500 if end_n in path2 else 0) + len(path2)
                if score > best["score"]:
                    best["score"] = score
                    best["path"] = path2
                dfs(nxt, path2, total + c2)

        if start_n in pool:
            dfs(start_n, [start_n], 0)
        path = best["path"]
        if end_n in pool and end_n not in path and path and touches(g, path[-1], end_n):
            path.append(end_n)

    WIN = Window(right=CHAIN_NAME[ch])
    WIN.frozen = True
    WIN.head_line("  " + paint(title, C.B, C.WHITE))
    if wb:
        WIN.head_line("  " + paint(f"цель: дойти от Кошелька 1 до Кошелька 2 — звенья = только реальные переводы", C.GRAY))

    for j, node in enumerate(path):
        wline("   " + paint(f"[{label(node)}]", color(node), C.B))
        wline("   " + paint(show_addr(node), C.WHITE))
        if j >= len(path) - 1:
            continue
        nxt = path[j + 1]
        c_uv, a_uv = flow(g, node, nxt, ch)     # node -> nxt
        c_vu, a_vu = flow(g, nxt, node, ch)     # nxt -> node
        if c_vu > c_uv:
            frm, to, cc, aa = nxt, node, c_vu, a_vu
            inv_c, inv_a = c_uv, a_uv
        else:
            frm, to, cc, aa = node, nxt, c_uv, a_uv
            inv_c, inv_a = c_vu, a_vu
        fresh = freshest(g, node, nxt)
        when = (" · посл. " + fmt_date(fresh["ts"])[:10]) if fresh else ""
        wline("        " + paint(T_V, C.GRAY))
        wline("        " + paint(DWN, C.GRAY) + " "
              + paint(f"шаг {j+1}", C.B, C.CYAN) + "  "
              + paint(f"{label(frm)} отправил {ARR} {label(to)}", C.WHITE, C.B))
        wline("           " + paint(f"{cc} {pl(cc, TX_W)} · {fmt_assets(aa)}{when}", C.YEL, C.B))
        if inv_c:
            wline("           " + paint(f"и обратно: {inv_c} {pl(inv_c, TX_W)} · {fmt_assets(inv_a)}", C.GRAY))
        if {node, nxt} == {x, y}:
            wline("           " + paint("◄◄ СВЯЗЬ ПОСРЕДНИКОВ МЕЖДУ СОБОЙ — главный стык", C.VIO, C.B))

    # стык не вошёл в линейную цепочку — показываем отдельным блоком
    if not inline_xy and cnt:
        wline("")
        wsep()
        wline("   " + paint("СВЯЗЬ ПОСРЕДНИКОВ МЕЖДУ СОБОЙ · ГЛАВНЫЙ СТЫК", C.B, C.VIO))
        wline("      " + paint(f"[{label(x)}]", C.VIO, C.B) + paint(f" {DBL} ", C.GRAY) + paint(f"[{label(y)}]", C.VIO, C.B))
        wline("      " + paint(show_addr(x), C.WHITE))
        wline("      " + paint(show_addr(y), C.WHITE))
        wline("      " + paint(f"переводов между ними: {cnt} · объём {fmt_assets(assets)}", C.YEL, C.B))

    wline("")
    wsep()
    top_label, bot_label = label(path[0]), label(path[-1])
    wline("   " + paint(f"Итог: прямая цепь сверху вниз  {top_label} {ARR} … {ARR} {bot_label}  ({len(path) - 1} {pl(len(path) - 1, ('шаг', 'шага', 'шагов'))}, все звенья on-chain).", C.GREEN, C.B))
    WIN.finish()
    WIN = None

# ----------------------------------------------------------------------
# Пайплайн
# ----------------------------------------------------------------------

def run_pipeline(args, a, b):
    global WIN
    if args.chain == "ton" and args.limit <= 150:
        args.limit = 400
    if not args.sleep:
        args.sleep = 1.1 if args.chain == "ton" else 0.45

    WIN = Window(right=CHAIN_NAME[args.chain])
    WIN.head_line("  " + paint("Кошелёк 1: ", C.CYAN) + paint(show_addr(a), C.B, C.CYAN))
    if b:
        WIN.head_line("  " + paint("Кошелёк 2: ", C.GREEN) + paint(show_addr(b), C.B, C.GREEN))
    src = "демо (оффлайн)" if args.demo else ("tonapi / toncenter · только прямые переводы" if args.chain == "ton" else "BlockCypher" + (" / Etherscan" if args.es_key else ""))
    WIN.head_line("  " + paint(f"Сеть: {CHAIN_NAME[args.chain]} · история до {args.limit} tx · контрагентов до {args.expand}"
                                + (f" · окно {args.days} дн" if args.days else " · вся история") + f" · {src}", C.GRAY))

    fetcher = Fetcher(args)
    cutoff = (int(time.time()) - args.days * 86400) if (args.days and not args.demo) else None
    try:
        res = analyze_web(fetcher, a, b, args, cutoff=cutoff)
        res["full_history"] = False
        enough = len([x for x in res["rank"] if res["cp"][x]["total"] > 0]) >= 2 or res["pairs"]
        if not enough and cutoff:
            step(f"в последние {args.days} дней пусто — смотрю ВСЮ историю")
            res = analyze_web(fetcher, a, b, args, cutoff=None)
            res["full_history"] = True
    except ApiFailure as e:
        wline("  " + paint(CRS + f" API не отвечает: {e}", C.RED))
        wline("  " + paint("Подсказка: --token / --es-key / --ton-key или меньше --limit/--expand", C.YEL))
        WIN.finish(); WIN = None
        return 1

    WIN.begin_final()
    web_body(res, args)
    WIN.finish()
    WIN = None

    if not res["pairs"]:
        print(paint("   Enter — назад", C.GRAY))
        prompt_line("")
        return 3

    print(paint("   Enter — показать цепочку по шагам", C.GRAY))
    if prompt_line("") == "0":
        return 0
    chain_screen(res, res["pairs"][0], args, "Ц Е П О Ч К А   П О   Ш А Г А М")

    if len(res["pairs"]) > 1:
        print(paint("   Enter — ВТОРАЯ связка (следующая по частоте)", C.GRAY))
        if prompt_line("") == "0":
            return 0
        chain_screen(res, res["pairs"][1], args, "В А Р И А Н Т  2 · Ц Е П О Ч К А")
    return 0

# ----------------------------------------------------------------------
# Меню / ввод
# ----------------------------------------------------------------------

def prompt_line(text=""):
    try:
        return input(paint(" › ", C.CYAN, C.B) + paint(text, C.WHITE)).strip()
    except (EOFError, KeyboardInterrupt):
        return "0"

def resolve_and_check(args, raw_a, raw_b=None):
    raws = [raw_a] + ([raw_b] if raw_b else [])
    chains = [r for r in (detect_chain(x) for x in raws) if r]
    if len(set(chains)) > 1:
        print(paint(CRS + " Кошельки из разных сетей — пусть будут в одной.", C.RED))
        return 2
    if not chains:
        print(paint(CRS + " Не удалось определить сеть. Укажите вручную: --chain btc|eth|ton", C.RED))
        return 2
    chain = chains[0]
    args.chain = chain
    print(paint("  " + CHK + f" Сеть определена автоматически: {CHAIN_NAME[chain]}", C.GREEN))
    out = []
    for label, r in zip(("Кошелёк 1", "Кошелёк 2"), raws):
        addr = normalize(chain, r)
        ok_format = full(RX_ETH, addr) if chain == "eth" else (
            full(RX_TON_RAW, addr) if chain == "ton" else full(RX_BTC, addr))
        if not ok_format:
            print(paint(CRS + f" Неверный формат адреса для {label} ({CHAIN_NAME[chain]})", C.RED))
            return 2
        register_disp(addr, r)
        out.append(addr)
    if len(out) == 2 and out[0] == out[1]:
        print(paint(CRS + " Адреса совпадают", C.RED))
        return 2
    return tuple(out)

def run_pair_flow(args, demo=False):
    if demo:
        args.chain = args.chain if args.chain != "auto" else "ton"
        args.demo = True
        _, da, db = build_demo(args.chain)
        code = run_pipeline(args, da, db)
        args.demo = False
        prompt_line("Enter — в меню ")
        return code
    print()
    w1 = prompt_line("Вставь адрес Кошелька 1 и нажми Enter: ")
    if not w1:
        return 2
    w2 = prompt_line("Кошелёк 2 — конечная цель цепочки (можно пусто): ")
    checked = resolve_and_check(args, w1, w2 or None)
    if isinstance(checked, int):
        prompt_line("Enter — в меню ")
        return checked
    code = run_pipeline(args, *checked)
    prompt_line("Enter — в меню ")
    return code

def settings_menu(args):
    while True:
        clear_screen()
        print()
        print(_fb(T_TL + T_H * (WIN_W - 2) + T_TR))
        wline(paint("  Н А С Т Р О Й К И   П А У Т И Н Ы", C.B, C.WHITE))
        wsep()
        wline("  " + paint(f"[1] Контрагентов изучать: {args.expand}", C.WHITE))
        wline("  " + paint(f"[2] История на кошелёк: {args.limit} tx", C.WHITE))
        wline("  " + paint(f"[3] Окно свежести: {args.days} дн  (0 = вся история)", C.WHITE))
        wline("  " + paint("[0] Назад", C.GRAY))
        print(_fb(T_BL + T_H * (WIN_W - 2) + T_BR))
        ch = prompt_line("")
        if ch == "1":
            v = prompt_line("число 2-40: ")
            if v.isdigit() and 2 <= int(v) <= 40:
                args.expand = int(v)
        elif ch == "2":
            v = prompt_line("число 50-2000: ")
            if v.isdigit() and 50 <= int(v) <= 2000:
                args.limit = int(v)
        elif ch == "3":
            v = prompt_line("дней 1-3650 или 0 (вся история): ")
            if v.isdigit() and 0 <= int(v) <= 3650:
                args.days = int(v)
        else:
            return

def interactive_menu(args):
    while True:
        clear_screen()
        print()
        print(_fb(T_TL + T_H * (WIN_W - 2) + T_TR))
        wline("  " + paint("ChainTrace", C.GREEN, C.B) + paint(f"  v{VERSION} (seed-web) · by {AUTHOR}", C.GRAY))
        wsep()
        wline("   " + paint("[1] ", C.GREEN, C.B) + paint("Построить паутину вокруг кошелька", C.WHITE))
        wline("   " + paint("[2] ", C.GREEN, C.B) + paint("Пример на демо-данных (без интернета)", C.WHITE))
        wline("   " + paint("[3] ", C.GREEN, C.B) + paint("Настройки", C.WHITE))
        wline("   " + paint("[0] ", C.GREEN, C.B) + paint("Выход", C.WHITE))
        wsep()
        wline("   " + paint("главный кошелёк = с меньшим числом переводов · без обменов и свопов", C.GRAY))
        print(_fb(T_BL + T_H * (WIN_W - 2) + T_BR))
        ch = prompt_line("")
        if ch == "1":
            run_pair_flow(args, demo=False)
        elif ch == "2":
            run_pair_flow(args, demo=True)
        elif ch == "3":
            settings_menu(args)
        elif ch == "0":
            print(paint("  " + CHK + " Готово. Пока!", C.GREEN))
            return

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="wallet_link_analyzer.py",
        description="ChainTrace (seed-web) — паутина прямых переводов вокруг кошелька BTC/ETH/TON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("примеры:\n"
                "  python wallet_link_analyzer.py UQDXVX…\n"
                "  python wallet_link_analyzer.py UQDXVX… UQCE…\n"
                "  python wallet_link_analyzer.py --demo --chain ton\n"))
    p.add_argument("wallet_a", nargs="?")
    p.add_argument("wallet_b", nargs="?")
    p.add_argument("--chain", choices=["auto", "btc", "eth", "ton"], default="auto")
    p.add_argument("--limit", type=int, default=150)
    p.add_argument("--expand", type=int, default=10)
    p.add_argument("--days", type=int, default=180,
                   help="смотреть только последние N дней; 0 = вся история (по умолчанию 180)")
    p.add_argument("--sleep", type=float, default=0.0)
    p.add_argument("--token", default=os.environ.get("BLOCKCYPHER_TOKEN", ""))
    p.add_argument("--es-key", default=os.environ.get("ETHERSCAN_KEY", ""))
    p.add_argument("--ton-key", default=os.environ.get("TONAPI_KEY", ""))
    p.add_argument("--demo", action="store_true")
    p.add_argument("--no-color", action="store_true")
    return p

def main():
    global COLOR
    args = build_parser().parse_args()
    COLOR = (not args.no_color) and ("NO_COLOR" not in os.environ)
    enable_win_ansi()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    enter_alt()
    try:
        if not args.demo and not args.wallet_a:
            interactive_menu(args)
            return 0
        if args.demo:
            args.chain = args.chain if args.chain != "auto" else "ton"
            _, da, db = build_demo(args.chain)
            return run_pipeline(args, da, db)
        checked = resolve_and_check(args, args.wallet_a.strip(), (args.wallet_b or "").strip() or None)
        if isinstance(checked, int):
            return checked
        return run_pipeline(args, *checked)
    except KeyboardInterrupt:
        print("\n" + paint(WRN + " прервано пользователем", C.YEL))
        return 130
    finally:
        leave_alt()

if __name__ == "__main__":
    sys.exit(main())
