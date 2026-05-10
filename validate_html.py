import json, re, sys, glob, os

# Find the latest HTML file
files = sorted(glob.glob("output/portfolio_report_*.html"))
if not files:
    print("No HTML files found")
    sys.exit(1)

html_file = files[-1]
print(f"Checking: {html_file}")

with open(html_file, encoding="utf-8") as f:
    content = f.read()

# Check if MULTI_TF_DATA_JSON placeholder was replaced
if "{{MULTI_TF_DATA_JSON}}" in content:
    print("ERROR: Placeholder was NOT replaced! Template injection failed.")
    sys.exit(1)
else:
    print("OK: Placeholder was replaced")

# Extract the JSON data
m = re.search(r'const multiTfData = (\{.+?\});\s*\n', content, re.DOTALL)
if not m:
    print("ERROR: Could not find multiTfData assignment")
    sys.exit(1)

data_str = m.group(1)
print(f"Found data of length: {len(data_str):,} chars")

try:
    data = json.loads(data_str)
    print("OK: JSON is VALID")
    for tf, assets in data.items():
        print(f"  Timeframe '{tf}': {len(assets)} assets")
        if assets:
            a = assets[0]
            print(f"    First asset: {a['symbol']}, {len(a.get('chart_data',[]))} candles, {len(a.get('trades_history',[]))} trades")
except json.JSONDecodeError as e:
    print(f"ERROR: JSON parse failed: {e}")
    # Show context around the error
    pos = e.pos
    print(f"Context (chars {pos-100} to {pos+100}):")
    print(repr(data_str[max(0,pos-100):pos+100]))
