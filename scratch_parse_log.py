import re

log_path = r"\\wsl.localhost\Ubuntu\home\learning\projects\mats-code\output\log_portfolio_20260515_1835.txt"

with open(log_path, "r", encoding="utf-8") as f:
    content = f.read()

# Let's find all backtest complete blocks
pattern = re.compile(
    r"=== Backtest Complete: (?P<symbol>[A-Z0-9_/]+) ===\s+Total Return\s+:\s+(?P<return>[-+][0-9.]+)%\s+Trades\s+:\s+(?P<trades>\d+) \(W:(?P<wins>\d+) L:(?P<losses>\d+)\)\s+Win Rate\s+:\s+(?P<winrate>[0-9.]+)%\s+Avg PnL/trade:\s+(?P<pnl>[-+][0-9.]+) USD\s+Max Drawdown\s+:\s+(?P<dd>[0-9.]+)%\s+Final Capital:\s+(?P<capital>[0-9.]+) USD"
)

matches = pattern.finditer(content)
results = []
for m in matches:
    results.append(m.groupdict())

print(f"Total backtests parsed: {len(results)}")
print("\nNegative Return Backtests:")
print(f"{'Symbol':<15} | {'Total Return':<12} | {'Trades':<6} | {'Win Rate':<8} | {'Avg PnL':<10} | {'Max DD':<6} | {'Final Cap':<10}")
print("-" * 80)
neg_count = 0
for r in results:
    ret_val = float(r["return"])
    if ret_val < 0:
        neg_count += 1
        print(f"{r['symbol']:<15} | {r['return']:<12}% | {r['trades']:<6} | {r['winrate']:<8}% | {r['pnl']:<10} | {r['dd']:<6}% | {r['capital']:<10}")

print(f"\nNumber of negative return assets: {neg_count} out of {len(results)}")
