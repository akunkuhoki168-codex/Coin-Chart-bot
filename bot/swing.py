"""Exact port of coin-chart v7.0 / v7.1 ATR-adaptive zigzag BUY/SELL logic.

The control flow, thresholds, and IEEE-754 operations follow the JavaScript
implementation in index.html (detectSwingSignals and helpers) so signals match
bar-for-bar: pivot time, side, and price.
"""
from __future__ import annotations

import math
from typing import Any, Optional

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

MIN_PCT = {"1m": 1, "5m": 1.5, "15m": 1.2, "1h": 2, "4h": 2.5, "1d": 3.5}


def is_finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def js_round(n: float) -> int:
    """Match JavaScript Math.round (half toward +infinity)."""
    return int(math.floor(n + 0.5))


def rsi_val(g: float, l: float) -> float:
    if l == 0:
        return 100.0
    if g == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + g / l)


def rsi_arr(candles: list[dict], period: int = 14) -> list[float]:
    n = len(candles)
    out = [float("nan")] * n
    avg_g = 0.0
    avg_l = 0.0
    for i in range(1, n):
        diff = candles[i]["close"] - candles[i - 1]["close"]
        g = max(0.0, diff)
        l = max(0.0, -diff)
        if i <= period:
            avg_g += g
            avg_l += l
            if i == period:
                avg_g /= period
                avg_l /= period
                out[i] = rsi_val(avg_g, avg_l)
        else:
            avg_g = (avg_g * (period - 1) + g) / period
            avg_l = (avg_l * (period - 1) + l) / period
            out[i] = rsi_val(avg_g, avg_l)
    return out


def true_range_arr(candles: list[dict]) -> list[float]:
    n = len(candles)
    out = [0.0] * n
    for i in range(n):
        c = candles[i]
        if i == 0:
            out[i] = c["high"] - c["low"]
            continue
        p = candles[i - 1]["close"]
        out[i] = max(c["high"] - c["low"], abs(c["high"] - p), abs(c["low"] - p))
    return out


def atr_arr(candles: list[dict], period: int = 14) -> list[float]:
    period = period or 14
    tr = true_range_arr(candles)
    n = len(tr)
    out = [float("nan")] * n
    prev = float("nan")
    seed = 0.0
    count = 0
    for i in range(n):
        if not is_finite(tr[i]):
            out[i] = float("nan")
            continue
        if count < period:
            seed += tr[i]
            count += 1
            if count == period:
                prev = seed / period
                out[i] = prev
            else:
                out[i] = float("nan")
        else:
            prev = (prev * (period - 1) + tr[i]) / period
            out[i] = prev
    return out


def last_closed_index(candles: list[dict], tf: str, now_ms: Optional[float] = None) -> int:
    if not candles:
        return -1
    last = len(candles) - 1
    interval = INTERVAL_MS.get(tf, 60_000)
    now = now_ms if now_ms is not None else _now_ms()
    if candles[last]["time"] * 1000 + interval > now + 500:
        return last - 1
    return last


def _now_ms() -> float:
    import time
    return time.time() * 1000.0


def swing_params(tf: str, sensitivity: str = "medium") -> dict:
    sens = sensitivity or "medium"
    k = 5.0
    min_bars = 3
    if sens == "high":
        k = 4.5
        min_bars = 3
    elif sens == "low":
        k = 7.0
        min_bars = 4
    min_pct = MIN_PCT.get(tf, 1.5)
    if not is_finite(min_pct):
        min_pct = 1.5
    if sens == "high":
        min_pct *= 0.8
    if sens == "low":
        min_pct *= 1.25
    return {"k": k, "minBars": min_bars, "minPct": min_pct, "sens": sens}


def swing_thresh(atr: list[float], i: int, pivot_price: float, pivot_i: int, k: float, min_pct: float) -> float:
    a = atr[i] if is_finite(atr[i]) else (atr[pivot_i] if pivot_i >= 0 and is_finite(atr[pivot_i]) else 0.0)
    t = (k * a) if a else 0.0
    if min_pct > 0 and pivot_price > 0:
        t = max(t, pivot_price * min_pct / 100.0)
    return max(t, 0.0)


def swing_hl(candles: list[dict], i: int, atr: list[float], clip: float = 3.0) -> dict:
    if i < 0 or i >= len(candles) or not candles[i]:
        return {"high": float("nan"), "low": float("nan")}
    c = candles[i]
    hi = c["high"]
    lo = c["low"]
    clip = clip if is_finite(clip) else 3.0
    a = atr[i - 1] if i > 0 and is_finite(atr[i - 1]) else (atr[i] if is_finite(atr[i]) else 0.0)
    if a > 0 and clip > 0:
        body_hi = max(c["open"], c["close"])
        body_lo = min(c["open"], c["close"])
        hi = min(hi, body_hi + clip * a)
        lo = max(lo, body_lo - clip * a)
        if lo > hi:
            lo = body_lo
            hi = body_hi
    return {"high": hi, "low": lo}


def compute_swing_pivots(candles: list[dict], end: int, atr: list[float], params: dict) -> dict:
    start = 14
    mode = "init"
    pivots: list[dict] = []
    k = params["k"]
    min_bars = params["minBars"]
    min_pct = params["minPct"]
    developing = None
    if not candles or end < start + 2:
        return {"pivots": pivots, "developing": None, "mode": mode}

    hl = swing_hl(candles, 0, atr, 3)
    hi_i = 0
    hi = hl["high"]
    lo_i = 0
    lo = hl["low"]

    def confirm(kind: str, idx: int, price: float, conf_i: int) -> None:
        pivots.append({"kind": kind, "i": idx, "price": price, "conf": conf_i, "lag": conf_i - idx})

    def seed_high_from(frm: int, to: int) -> None:
        nonlocal hi, hi_i, hl
        hl = swing_hl(candles, frm, atr, 3)
        hi = hl["high"]
        hi_i = frm
        for j in range(frm, to + 1):
            hl = swing_hl(candles, j, atr, 3)
            if hl["high"] >= hi:
                hi = hl["high"]
                hi_i = j

    def seed_low_from(frm: int, to: int) -> None:
        nonlocal lo, lo_i, hl
        hl = swing_hl(candles, frm, atr, 3)
        lo = hl["low"]
        lo_i = frm
        for j in range(frm, to + 1):
            hl = swing_hl(candles, j, atr, 3)
            if hl["low"] <= lo:
                lo = hl["low"]
                lo_i = j

    for i in range(1, end + 1):
        hl = swing_hl(candles, i, atr, 3)
        if mode == "init":
            if hl["high"] >= hi:
                hi = hl["high"]
                hi_i = i
            if hl["low"] <= lo:
                lo = hl["low"]
                lo_i = i
            atr_ready = is_finite(atr[i])
            conf_low = (
                atr_ready
                and (hl["high"] - lo) >= swing_thresh(atr, i, lo, lo_i, k, min_pct)
                and (i - lo_i) >= min_bars
            )
            conf_high = (
                atr_ready
                and (hi - hl["low"]) >= swing_thresh(atr, i, hi, hi_i, k, min_pct)
                and (i - hi_i) >= min_bars
            )
            if conf_low and ((not conf_high) or lo_i <= hi_i):
                confirm("low", lo_i, lo, i)
                mode = "seek_high"
                seed_high_from(lo_i, i)
            elif conf_high:
                confirm("high", hi_i, hi, i)
                mode = "seek_low"
                seed_low_from(hi_i, i)
        elif mode == "seek_high":
            if hl["high"] >= hi:
                hi = hl["high"]
                hi_i = i
            if (
                is_finite(atr[i])
                and (hi - hl["low"]) >= swing_thresh(atr, i, hi, hi_i, k, min_pct)
                and (i - hi_i) >= min_bars
            ):
                confirm("high", hi_i, hi, i)
                mode = "seek_low"
                seed_low_from(hi_i, i)
        else:
            if hl["low"] <= lo:
                lo = hl["low"]
                lo_i = i
            if (
                is_finite(atr[i])
                and (hl["high"] - lo) >= swing_thresh(atr, i, lo, lo_i, k, min_pct)
                and (i - lo_i) >= min_bars
            ):
                confirm("low", lo_i, lo, i)
                mode = "seek_high"
                seed_high_from(lo_i, i)

    if mode == "seek_high":
        developing = {"kind": "high", "i": hi_i, "price": hi}
    elif mode == "seek_low":
        developing = {"kind": "low", "i": lo_i, "price": lo}
    return {"pivots": pivots, "developing": developing, "mode": mode}


def simple_reversal_at(candles: list[dict], i: int, direction: str) -> Optional[dict]:
    if i < 1 or i >= len(candles):
        return None
    c = candles[i]
    p = candles[i - 1]
    body = abs(c["close"] - c["open"])
    rng = max(c["high"] - c["low"], 1e-12)
    upper = c["high"] - max(c["open"], c["close"])
    lower = min(c["open"], c["close"]) - c["low"]
    bull = c["close"] > c["open"]
    bear = c["close"] < c["open"]
    p_body = abs(p["close"] - p["open"])
    if direction == "bull":
        if p["close"] < p["open"] and bull and p_body > 0 and body > p_body and c["open"] <= p["close"] and c["close"] >= p["open"]:
            return {"name": "Bullish Engulfing", "pri": 90}
        if lower >= 2.2 * max(body, 1e-12) and upper <= body * 0.5 and body <= 0.4 * rng and c["close"] >= c["low"] + rng * 0.55:
            return {"name": "Hammer", "pri": 70}
    else:
        if p["close"] > p["open"] and bear and p_body > 0 and body > p_body and c["open"] >= p["close"] and c["close"] <= p["open"]:
            return {"name": "Bearish Engulfing", "pri": 90}
        if upper >= 2.2 * max(body, 1e-12) and lower <= body * 0.5 and body <= 0.4 * rng and c["close"] <= c["low"] + rng * 0.45:
            return {"name": "Shooting Star", "pri": 70}
    return None


def swing_candle_bonus(candles: list[dict], pivot_i: int, direction: str) -> str:
    frm = max(1, pivot_i - 1)
    to = min(len(candles) - 1, pivot_i + 1)
    name = ""
    pri = -1
    for j in range(frm, to + 1):
        hit = simple_reversal_at(candles, j, direction)
        if hit and hit["pri"] > pri:
            pri = hit["pri"]
            name = hit["name"]
    return name


def vol_sma_prev(candles: list[dict], i: int, period: int = 20) -> float:
    if i < period:
        return float("nan")
    s = 0.0
    for k in range(i - period, i):
        s += candles[k]["volume"]
    return s / period


def rate_swing(direction: str, pivot_i: int, candles: list[dict], rsis: list[float], prev_same: Optional[dict]) -> dict:
    stars = 0
    reasons: list[str] = []
    rsi = rsis[pivot_i]
    div = False
    if prev_same and is_finite(rsi) and is_finite(rsis[prev_same["i"]]):
        if direction == "bull" and candles[pivot_i]["low"] < prev_same["price"] and rsi > rsis[prev_same["i"]]:
            div = True
        if direction == "bear" and candles[pivot_i]["high"] > prev_same["price"] and rsi < rsis[prev_same["i"]]:
            div = True
    if direction == "bull" and ((is_finite(rsi) and rsi < 40) or div):
        stars += 1
        reasons.append("Bullish RSI divergence" if div else ("RSI " + str(js_round(rsi))))
    elif direction == "bear" and ((is_finite(rsi) and rsi > 60) or div):
        stars += 1
        reasons.append("Bearish RSI divergence" if div else ("RSI " + str(js_round(rsi))))
    candle_name = swing_candle_bonus(candles, pivot_i, direction)
    if candle_name:
        stars += 1
        reasons.append(candle_name)
    vs = vol_sma_prev(candles, pivot_i, 20)
    if is_finite(vs) and vs > 0 and candles[pivot_i]["volume"] >= 1.2 * vs:
        stars += 1
        reasons.append("Volume spike")
    if stars > 3:
        stars = 3
    return {"stars": stars, "reasons": reasons}


def empty_swing_stats() -> dict:
    return {
        "n": 0, "buys": 0, "sells": 0, "avgLag": None, "medLag": None,
        "local20Buy": None, "local20Sell": None, "avgSwingPct": None, "avgSwingAtr": None,
    }


def detect_swing_signals(
    candles: list[dict],
    tf: str,
    sensitivity: str = "medium",
    swing_early: bool = True,
    now_ms: Optional[float] = None,
) -> dict:
    out: list[dict] = []
    if not candles or len(candles) < 20:
        return {"signals": out, "provisional": None, "stats": empty_swing_stats()}
    last = len(candles) - 1
    last_closed = last_closed_index(candles, tf, now_ms)
    forming = last_closed < last
    if last_closed < 20:
        return {"signals": out, "provisional": None, "stats": empty_swing_stats()}
    atr = atr_arr(candles, 14)
    params = swing_params(tf, sensitivity)
    pack = compute_swing_pivots(candles, last_closed, atr, params)
    if forming and pack["developing"]:
        live = swing_hl(candles, last, atr, 3)
        if pack["mode"] == "seek_high" and live["high"] >= pack["developing"]["price"]:
            pack["developing"] = {"kind": "high", "i": last, "price": live["high"]}
        elif pack["mode"] == "seek_low" and live["low"] <= pack["developing"]["price"]:
            pack["developing"] = {"kind": "low", "i": last, "price": live["low"]}
    rsis = rsi_arr(candles, 14)
    pivots = pack["pivots"]
    for i, p in enumerate(pivots):
        direction = "bull" if p["kind"] == "low" else "bear"
        prev_same = pivots[i - 2] if i >= 2 else None
        rate = rate_swing(direction, p["i"], candles, rsis, prev_same)
        nxt = pivots[i + 1] if i + 1 < len(pivots) else None
        if nxt:
            pct = js_round(((nxt["price"] - p["price"]) / p["price"]) * 10000) / 100.0 if p["price"] else None
            label = ((("+" if pct >= 0 else "") + str(pct) + "% to next " + ("BUY" if nxt["kind"] == "low" else "SELL")) if is_finite(pct) else "")
        elif pack["developing"] and pack["developing"]["kind"] != p["kind"]:
            pct = js_round(((pack["developing"]["price"] - p["price"]) / p["price"]) * 10000) / 100.0 if p["price"] else None
            label = ((("+" if pct >= 0 else "") + str(pct) + "% so far") if is_finite(pct) else "")
        else:
            pct = None
            label = ""
        rate["reasons"] = ["Lag " + str(p["lag"]) + " bar" + ("" if p["lag"] == 1 else "s")] + rate["reasons"]
        out.append({
            "index": p["i"],
            "time": candles[p["i"]]["time"],
            "price": p["price"],
            "dir": direction,
            "id": "buy" if direction == "bull" else "sell",
            "name": "BUY" if direction == "bull" else "SELL",
            "short": "BUY" if direction == "bull" else "SELL",
            "forming": False,
            "provisional": False,
            "confirmIndex": p["conf"],
            "confirmTime": candles[p["conf"]]["time"] if p["conf"] < len(candles) and candles[p["conf"]] else candles[p["i"]]["time"],
            "lag": p["lag"],
            "stars": rate["stars"],
            "reasons": rate["reasons"],
            "nextMovePct": pct,
            "nextMoveLabel": label,
            "swingKind": "bottom" if p["kind"] == "low" else "top",
            "unified": True,
        })
    prov = None
    if swing_early is not False and pack["developing"] and pack["developing"]["i"] >= 0:
        direction = "bull" if pack["developing"]["kind"] == "low" else "bear"
        dev = pack["developing"]
        prov = {
            "index": dev["i"],
            "time": candles[dev["i"]]["time"],
            "price": dev["price"],
            "dir": direction,
            "id": "buy" if direction == "bull" else "sell",
            "name": "BUY?" if direction == "bull" else "SELL?",
            "short": "BUY?" if direction == "bull" else "SELL?",
            "forming": forming and dev["i"] == last,
            "provisional": True,
            "lag": None,
            "stars": 0,
            "reasons": ["Developing — not confirmed"],
            "swingKind": "bottom" if dev["kind"] == "low" else "top",
            "unified": True,
        }
    return {"signals": out, "provisional": prov, "stats": None}
