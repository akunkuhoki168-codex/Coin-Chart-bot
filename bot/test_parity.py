#!/usr/bin/env python3
"""Compare Python swing signals to the JavaScript engine on the same klines."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent
ROOT = BOT_DIR.parent
sys.path.insert(0, str(BOT_DIR))
from swing import detect_swing_signals  # noqa: E402

CASES = [
    ("PUMPUSDT", "5m"),
    ("ANKRUSDT", "1d"),
    ("BTCUSDT", "1h"),
]
REST_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
]


def fetch_klines(symbol: str, tf: str, dest: Path) -> None:
    last = None
    for base in REST_BASES:
        url = f"{base}/api/v3/klines?symbol={symbol}&interval={tf}&limit=1000"
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                data = r.read()
            json.loads(data)
            dest.write_bytes(data)
            return
        except Exception as e:
            last = e
    raise RuntimeError(f"could not fetch {symbol} {tf}: {last}")


def load_candles(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    out = []
    for k in raw[:1000]:
        out.append({
            "time": int(k[0]) // 1000,
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return out


def js_detect(html: Path, klines: Path, tf: str, sens: str, now_ms: float) -> dict:
    r = subprocess.run(
        ["node", str(BOT_DIR / "js_gold.js"), str(html), str(klines), tf, sens, str(now_ms)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)
    return json.loads(r.stdout)


def main() -> int:
    html = ROOT / "index.html"
    if not html.exists():
        print("index.html not found next to bot/", file=sys.stderr)
        return 2
    cache = Path("/tmp")
    now_ms = time.time() * 1000
    fetch = "--cached" not in sys.argv
    fail = 0
    for sym, tf in CASES:
        dest = cache / f"klines_{sym}_{tf}.json"
        if fetch or not dest.exists():
            print(f"fetch {sym} {tf} …")
            fetch_klines(sym, tf, dest)
        candles = load_candles(dest)
        py = detect_swing_signals(candles, tf, "medium", True, now_ms)
        js = js_detect(html, dest, tf, "medium", now_ms)
        ps, js_sigs = py["signals"], js["signals"]
        print(f"{sym} {tf}: Python {len(ps)}  JS {len(js_sigs)}  bars {len(candles)}")
        diffs = 0
        if len(ps) != len(js_sigs):
            diffs += 1
            print(f"  COUNT MISMATCH py={len(ps)} js={len(js_sigs)}")
        for i in range(min(len(ps), len(js_sigs))):
            a, b = ps[i], js_sigs[i]
            if not (a["time"] == b["time"] and a["dir"] == b["dir"] and a["price"] == b["price"]):
                diffs += 1
                print("  DIFF pivot", i, a["time"], a["dir"], a["price"], "vs", b["time"], b["dir"], b["price"])
            elif a.get("lag") != b.get("lag") or a.get("stars") != b.get("stars") or a.get("confirmTime") != b.get("confirmTime"):
                diffs += 1
                print("  DIFF meta", i, a, b)
        pp, jp = py.get("provisional"), js.get("provisional")
        if (pp is None) != (jp is None):
            diffs += 1
            print("  PROVISIONAL mismatch")
        elif pp and (pp["time"] != jp["time"] or pp["dir"] != jp["dir"] or pp["price"] != jp["price"]):
            diffs += 1
            print("  PROVISIONAL DIFF", pp, jp)
        if diffs:
            fail += 1
            print("  FAIL")
        else:
            last = ps[-1] if ps else None
            extra = f" last {last['name']} @ {last['price']} lag {last['lag']}" if last else ""
            print("  MATCH" + extra)
    print("OVERALL", "OK" if not fail else f"FAIL ({fail} cases)")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
