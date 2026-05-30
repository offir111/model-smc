"""
MODEL SMC — Show Simulation Results
Run: python show_results.py
"""
import json, os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def load(fname):
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path): return None
    with open(path, encoding="utf-8") as f: return json.load(f)

portfolio  = load("portfolio.json")
positions  = load("open_positions.json") or {}

if not portfolio:
    print("No data yet. Run smc_simulator.py first.")
    exit()

p          = portfolio
s          = p["stats"]
total_val  = round(p["available"] + p["in_trades"], 2)
total_pct  = round(p["total_pnl"] / p["starting_balance"] * 100, 2)
start_dt   = datetime.fromisoformat(p["created"])
days_run   = max(0.001, (datetime.now() - start_dt).total_seconds() / 86400)

print(f"\n{'='*60}")
print(f"  MODEL SMC — Smart Money Concept")
print(f"  Sim started: {p['created'][:10]}  |  Running: {days_run:.1f} days")
print(f"{'='*60}")
print(f"\n  💼 Portfolio Summary")
print(f"  Balance    : ${total_val:,.2f}  (started: ${p['starting_balance']:,.2f})")
print(f"  P&L        : ${p['total_pnl']:+.2f}  ({total_pct:+.1f}%)")
print(f"  Available  : ${p['available']:,.2f}  |  In trades: ${p['in_trades']:,.2f}")

if s["total"] > 0:
    print(f"\n  📊 Statistics")
    print(f"  Trades     : {s['total']}  ({s['wins']}W / {s['losses']}L / {s['timeouts']}T)")
    print(f"  Win rate   : {s['win_rate']}%")
    print(f"  Avg win    : +{s['avg_win_pct']:.2f}%  |  Avg loss: {s['avg_loss_pct']:.2f}%")
    pf = s.get('profit_factor', 0)
    pf_tag = "✅ Good" if pf >= 1.5 else ("⚠️ Low" if pf > 0 else "—")
    print(f"  PF         : {pf:.2f}  {pf_tag}")

if positions:
    print(f"\n  🔓 Open Positions ({len(positions)})")
    for key, pos in positions.items():
        open_dt   = datetime.fromisoformat(pos["open_time"])
        held_h    = (datetime.now() - open_dt).total_seconds() / 3600
        print(f"  {pos['symbol']:<8} entry=${pos['entry_price']:.2f}  "
              f"target=${pos['target_price']:.2f}  stop=${pos['stop_price']:.2f}  "
              f"held={held_h:.1f}h")
else:
    print("\n  🔓 No open positions")

# Show last 10 trades
trades = p.get("trades", [])
if trades:
    print(f"\n  📋 Last {min(10, len(trades))} trades:")
    for t in trades[-10:]:
        emoji = "💚" if t["result"] == "win" else ("🔴" if t["result"] == "loss" else "⏰")
        print(f"  {emoji} {t['symbol']:<8} {t['reason']:<8}  "
              f"P&L: ${t['pnl_usd']:+.2f}  ({t['price_pct']:+.1f}%)  "
              f"entry=${t['entry_price']:.2f}  exit=${t['exit_price']:.2f}")

print(f"\n{'='*60}\n")
