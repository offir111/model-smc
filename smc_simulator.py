"""
MODEL SMC — Smart Money Concept Simulator
==========================================
Strategy : Gap-up detection on institutional stocks
           BUY when gap >= 1.5% vs previous close
           Target: +4% | Stop: -2% | Trade: $300
Stocks   : AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, JPM, V, BRK.B
Data     : Yahoo Finance (yfinance) — free, no API key
Run      : Every 15 minutes via GitHub Actions
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import json
import os
import time
from datetime import datetime

try:
    import yfinance as yf
    import requests
    HAS_YF = True
except ImportError:
    HAS_YF = False
    print("WARNING: yfinance not installed. Using fallback.")

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────
SYMBOLS_DISPLAY = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
                   "META", "TSLA", "JPM", "V", "BRK.B"]
# yfinance uses BRK-B (not BRK.B)
YF_SYMBOLS = [s.replace(".", "-") for s in SYMBOLS_DISPLAY]

TARGET_PCT     = 4.0     # % profit target
STOP_PCT       = 2.0     # % stop loss
MIN_GAP_PCT    = 1.5     # % gap vs prev close to trigger entry
TRADE_USD      = 300     # $ per trade
STARTING_BAL   = 10000   # $ starting balance
MAX_OPEN       = 5       # max simultaneous positions
MAX_HOLD_HOURS = 8       # hours before timeout close

DATA_DIR         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PORTFOLIO_FILE   = os.path.join(DATA_DIR, "portfolio.json")
POSITIONS_FILE   = os.path.join(DATA_DIR, "open_positions.json")

# ─────────────────────────────────────────────────────────────────
# PRICE FETCHING
# ─────────────────────────────────────────────────────────────────

def fetch_stock_yf(yf_sym):
    """Fetch current price + prev close using yfinance"""
    try:
        ticker = yf.Ticker(yf_sym)
        fast = ticker.fast_info
        price    = float(fast.last_price)
        prev_cl  = float(fast.previous_close) if fast.previous_close else price
        gap_pct  = round((price - prev_cl) / prev_cl * 100, 2) if prev_cl else 0.0
        return {"price": price, "prev_close": prev_cl, "gap_pct": gap_pct}
    except Exception as e:
        print(f"    yf error {yf_sym}: {e}")
        return None


def fetch_stock_fallback(display_sym):
    """Yahoo Finance REST API fallback (no library needed)"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{display_sym}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params={"interval": "1d", "range": "2d"},
                         headers=headers, timeout=10)
        d = r.json()
        meta = d["chart"]["result"][0]["meta"]
        price   = float(meta["regularMarketPrice"])
        prev_cl = float(meta.get("previousClose") or meta.get("chartPreviousClose") or price)
        gap_pct = round((price - prev_cl) / prev_cl * 100, 2) if prev_cl else 0.0
        return {"price": price, "prev_close": prev_cl, "gap_pct": gap_pct}
    except Exception as e:
        print(f"    fallback error {display_sym}: {e}")
        return None


def get_all_prices():
    """Returns dict: {display_sym: {price, prev_close, gap_pct}}"""
    results = {}
    for i, (yf_sym, disp_sym) in enumerate(zip(YF_SYMBOLS, SYMBOLS_DISPLAY)):
        print(f"  Fetching {disp_sym}...", end=" ", flush=True)
        data = None
        if HAS_YF:
            data = fetch_stock_yf(yf_sym)
        if data is None:
            data = fetch_stock_fallback(disp_sym)
        if data:
            results[disp_sym] = data
            print(f"${data['price']:.2f}  gap={data['gap_pct']:+.2f}%  "
                  f"{'📈' if data['gap_pct'] >= MIN_GAP_PCT else '—'}")
        else:
            print("N/A")
        time.sleep(0.2)
    return results

# ─────────────────────────────────────────────────────────────────
# PORTFOLIO
# ─────────────────────────────────────────────────────────────────

def load_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        return None
    try:
        with open(PORTFOLIO_FILE, encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def init_portfolio():
    os.makedirs(DATA_DIR, exist_ok=True)
    p = {
        "starting_balance": STARTING_BAL,
        "available":        float(STARTING_BAL),
        "in_trades":        0.0,
        "total_pnl":        0.0,
        "high_watermark":   float(STARTING_BAL),
        "created":          datetime.now().isoformat(),
        "last_updated":     datetime.now().isoformat(),
        "trades": [],
        "stats": {
            "total": 0, "wins": 0, "losses": 0, "timeouts": 0,
            "win_rate": 0.0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
            "profit_factor": 0.0,
        },
    }
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)
    print(f"  ✅ SMC Portfolio created — Balance: ${STARTING_BAL:,.2f}")
    return p


def save_portfolio(p):
    p["last_updated"] = datetime.now().isoformat()
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)

# ─────────────────────────────────────────────────────────────────
# POSITIONS
# ─────────────────────────────────────────────────────────────────

def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return {}
    try:
        with open(POSITIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_positions(positions):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2, ensure_ascii=False)

# ─────────────────────────────────────────────────────────────────
# CLOSE POSITION + STATS UPDATE
# ─────────────────────────────────────────────────────────────────

def close_position_and_log(pos_key, pos, exit_price, reason, portfolio):
    entry       = pos["entry_price"]
    trade_amt   = pos["trade_amount"]
    price_pct   = round((exit_price - entry) / entry * 100, 2) if entry else 0
    pnl_usd     = round(price_pct / 100 * trade_amt, 2)
    returned    = round(trade_amt + pnl_usd, 2)

    portfolio["available"] = round(portfolio["available"] + returned, 2)
    portfolio["in_trades"] = round(max(0, portfolio["in_trades"] - trade_amt), 2)
    portfolio["total_pnl"] = round(portfolio["total_pnl"] + pnl_usd, 2)

    # Determine result label
    if reason == "TIMEOUT":
        result_lbl = "timeout"
    elif pnl_usd >= 0:
        result_lbl = "win"
    else:
        result_lbl = "loss"

    s = portfolio["stats"]
    s["total"] += 1
    if result_lbl == "win":     s["wins"]     += 1
    elif result_lbl == "loss":  s["losses"]   += 1
    else:                       s["timeouts"] += 1
    s["win_rate"] = round(s["wins"] / s["total"] * 100, 1) if s["total"] else 0

    # Profit factor
    pf_wins   = [t["pnl_usd"] for t in portfolio["trades"] if t["pnl_usd"] > 0]
    pf_losses = [abs(t["pnl_usd"]) for t in portfolio["trades"] if t["pnl_usd"] < 0]
    if pnl_usd > 0: pf_wins.append(pnl_usd)
    elif pnl_usd < 0: pf_losses.append(abs(pnl_usd))
    total_won  = sum(pf_wins)
    total_lost = sum(pf_losses)
    s["profit_factor"] = (round(total_won / total_lost, 2)
                          if total_lost > 0 else (99.0 if total_won > 0 else 0.0))

    # Avg win/loss
    all_wins   = [t["price_pct"] for t in portfolio["trades"] if t["result"] == "win"]
    all_losses = [t["price_pct"] for t in portfolio["trades"] if t["result"] == "loss"]
    if result_lbl == "win": all_wins.append(price_pct)
    elif result_lbl == "loss": all_losses.append(price_pct)
    s["avg_win_pct"]  = round(sum(all_wins)   / len(all_wins),   2) if all_wins   else 0
    s["avg_loss_pct"] = round(sum(all_losses) / len(all_losses), 2) if all_losses else 0

    # High watermark
    total_val = round(portfolio["available"] + portfolio["in_trades"], 2)
    if total_val > portfolio.get("high_watermark", portfolio["starting_balance"]):
        portfolio["high_watermark"] = total_val

    # Append trade record
    portfolio["trades"].append({
        "symbol":      pos["symbol"],
        "entry_price": entry,
        "exit_price":  round(exit_price, 4),
        "qty":         pos.get("qty", 0),
        "trade_amount":trade_amt,
        "price_pct":   price_pct,
        "pnl_usd":     pnl_usd,
        "result":      result_lbl,
        "reason":      reason,
        "gap_pct":     pos.get("gap_pct", 0),
        "open_time":   pos.get("open_time", ""),
        "close_time":  datetime.now().isoformat(),
    })

    emoji = "💚" if pnl_usd >= 0 else "🔴"
    print(f"  {emoji} {pos['symbol']} CLOSED | {reason}  "
          f"P&L: ${pnl_usd:+.2f} ({price_pct:+.1f}%)  "
          f"Win rate: {s['win_rate']}%")

# ─────────────────────────────────────────────────────────────────
# MONITOR OPEN POSITIONS
# ─────────────────────────────────────────────────────────────────

def monitor_positions(price_map, portfolio):
    positions = load_positions()
    if not positions:
        return positions

    now = datetime.now()
    closed_keys = []

    for pos_key, pos in list(positions.items()):
        sym  = pos["symbol"]
        data = price_map.get(sym)
        if data is None:
            continue

        current    = data["price"]
        entry      = pos["entry_price"]
        target     = pos["target_price"]
        stop       = pos["stop_price"]
        open_time  = datetime.fromisoformat(pos["open_time"])
        held_hours = (now - open_time).total_seconds() / 3600
        price_pct  = (current - entry) / entry * 100

        print(f"  {sym:<8} entry=${entry:.2f}  now=${current:.2f}  "
              f"P&L={price_pct:+.1f}%  held={held_hours:.1f}h  "
              f"target=${target:.2f}  stop=${stop:.2f}")

        reason = None
        if current >= target:
            reason = "TARGET"
        elif current <= stop:
            reason = "STOP"
        elif held_hours >= MAX_HOLD_HOURS:
            reason = "TIMEOUT"

        if reason:
            close_position_and_log(pos_key, pos, current, reason, portfolio)
            closed_keys.append(pos_key)

    for k in closed_keys:
        del positions[k]

    if closed_keys:
        save_positions(positions)

    return positions

# ─────────────────────────────────────────────────────────────────
# SCAN FOR NEW ENTRIES
# ─────────────────────────────────────────────────────────────────

def run_scanner(price_map, portfolio):
    positions = load_positions()

    if len(positions) >= MAX_OPEN:
        print(f"  🔒 Max open positions ({MAX_OPEN}) reached — skipping scan")
        return

    # Find candidates: gap >= MIN_GAP_PCT and not already in position
    open_syms  = {pos["symbol"] for pos in positions.values()}
    candidates = []
    for sym, data in price_map.items():
        if data is None:
            continue
        if sym in open_syms:
            continue
        if data["gap_pct"] >= MIN_GAP_PCT:
            candidates.append((sym, data))

    if not candidates:
        print("  ⚪ No entry signals (no gap >= %.1f%%)" % MIN_GAP_PCT)
        return

    # Sort by gap size — biggest first
    candidates.sort(key=lambda x: x[1]["gap_pct"], reverse=True)
    print(f"  🎯 {len(candidates)} candidate(s) found:")

    for sym, data in candidates:
        if portfolio["available"] < TRADE_USD:
            print(f"  🔒 Insufficient balance: ${portfolio['available']:,.2f}")
            break
        if len(positions) >= MAX_OPEN:
            break

        price  = data["price"]
        qty    = max(1, int(TRADE_USD / price))
        cost   = round(qty * price, 2)

        target_px = round(price * (1 + TARGET_PCT / 100), 4)
        stop_px   = round(price * (1 - STOP_PCT   / 100), 4)

        pos_key = f"{sym}_{int(datetime.now().timestamp())}"
        positions[pos_key] = {
            "symbol":       sym,
            "entry_price":  round(price, 4),
            "target_price": target_px,
            "stop_price":   stop_px,
            "qty":          qty,
            "trade_amount": cost,
            "gap_pct":      data["gap_pct"],
            "open_time":    datetime.now().isoformat(),
        }

        portfolio["available"] = round(portfolio["available"] - cost, 2)
        portfolio["in_trades"] = round(portfolio["in_trades"] + cost, 2)

        print(f"  🟢 ENTRY: {sym} @ ${price:.2f}  Gap=+{data['gap_pct']:.1f}%  "
              f"Target=${target_px:.2f}  Stop=${stop_px:.2f}  Qty={qty}  Cost=${cost:.2f}")

    save_positions(positions)

# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  MODEL SMC — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Smart Money Concept | 10 Institutional Stocks")
    print(f"  Target: +{TARGET_PCT}%  Stop: -{STOP_PCT}%  Gap: +{MIN_GAP_PCT}%  Trade: ${TRADE_USD}")
    print(f"{'='*60}\n")

    # Load / init portfolio
    portfolio = load_portfolio()
    if portfolio is None:
        portfolio = init_portfolio()

    total_val  = round(portfolio["available"] + portfolio["in_trades"], 2)
    total_pct  = round(portfolio["total_pnl"] / portfolio["starting_balance"] * 100, 2)
    s          = portfolio["stats"]
    print(f"  💼 Portfolio: ${total_val:,.2f}  |  P&L: ${portfolio['total_pnl']:+.2f} ({total_pct:+.1f}%)")
    if s["total"] > 0:
        pf_tag = "✅" if s.get("profit_factor", 0) >= 1.5 else "⚠️"
        print(f"  📊 Win rate: {s['win_rate']}%  ({s['wins']}W/{s['losses']}L/{s['timeouts']}T)  "
              f"|  PF: {pf_tag}{s.get('profit_factor', 0):.2f}  |  Trades: {s['total']}")
    print()

    # Fetch all stock prices
    print("  📡 Fetching live stock prices...\n")
    price_map = get_all_prices()
    live_count = sum(1 for d in price_map.values() if d is not None)
    print(f"\n  {live_count}/{len(SYMBOLS_DISPLAY)} stocks fetched\n")

    if not price_map:
        print("  ⚠️ No price data — skipping this run")
        return

    # 1) Monitor existing positions
    positions = load_positions()
    if positions:
        print(f"  🔍 Monitoring {len(positions)} open position(s)...")
        positions = monitor_positions(price_map, portfolio)
        print()

    # 2) Scan for new entries (market hours check)
    from datetime import timezone as tz
    now_et_h = (datetime.now(tz.utc).hour - 4) % 24  # UTC-4 (EDT)
    market_open = 9 <= now_et_h < 16  # 9:30–16:00 ET approx

    if market_open:
        print(f"  🔍 Scanning for entry signals (gap >= {MIN_GAP_PCT}%)...")
        run_scanner(price_map, portfolio)
    else:
        print(f"  💤 Market closed (ET hour={now_et_h}) — monitoring only, no new entries")

    # Save portfolio
    save_portfolio(portfolio)

    # Final summary
    portfolio = load_portfolio()
    positions = load_positions()
    total_val  = round(portfolio["available"] + portfolio["in_trades"], 2)
    print(f"\n  💼 Portfolio: ${total_val:,.2f}  |  Open: {len(positions)}")
    s = portfolio["stats"]
    if s["total"] > 0:
        print(f"  📊 Trades: {s['total']}  |  Win rate: {s['win_rate']}%  |  Total P&L: ${portfolio['total_pnl']:+.2f}")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
