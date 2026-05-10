"""Quick sanity-check for the json-in-script-tag escape fix."""
import json
import subprocess
import sys

# Simulate the old vs new approach
test_data = {
    "15m": [{"symbol": "BTC/USDT", "name": "Test\u2028Name\u2029End", "score": 1.5}]
}

# Old approach (broken)
old_json = json.dumps(test_data)

# New approach (fixed)
new_json = (
    json.dumps(test_data)
    .replace("\u2028", "\\u2028")
    .replace("\u2029", "\\u2029")
    .replace("</script>", "<\\/script>")
)

print("=== Testing Unicode escape fix ===")
print(f"Input has U+2028: {chr(0x2028) in json.dumps(test_data)}")
print(f"Input has U+2029: {chr(0x2029) in json.dumps(test_data)}")
print()
print(f"Old JSON snippet: {old_json[:120]!r}")
print(f"New JSON snippet: {new_json[:120]!r}")

# Verify the new JSON still parses as valid JSON
reparsed = json.loads(new_json)
assert reparsed == test_data, "ERROR: re-parsed JSON does not match original!"
print()
print("OK: Fixed JSON re-parses to identical object.")

# Verify the new JSON does NOT contain raw U+2028 / U+2029
assert "\u2028" not in new_json, "ERROR: U+2028 still present!"
assert "\u2029" not in new_json, "ERROR: U+2029 still present!"
print("OK: No raw U+2028 or U+2029 in fixed JSON.")

# Generate a minimal test HTML
html = f"""<!DOCTYPE html>
<html>
<head><title>Fix Test</title></head>
<body>
<div id="out">Loading...</div>
<script>
const multiTfData = {new_json};
const count = Object.keys(multiTfData).length;
document.getElementById('out').textContent = 
    'OK: multiTfData has ' + count + ' timeframe(s), first TF has ' + 
    (multiTfData[Object.keys(multiTfData)[0]] || []).length + ' asset(s).';
</script>
</body>
</html>"""

test_file = "output/test_fix.html"
with open(test_file, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nOK: Test HTML written to {test_file}")
print("Open it in a browser to confirm 'OK: multiTfData has 1 timeframe(s), first TF has 1 asset(s).' is displayed.")
