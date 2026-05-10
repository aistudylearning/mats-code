import json

def process():
    file_path = r"C:\Users\learning\.gemini\antigravity\brain\8e5fd336-c6a8-4d15-b0ed-c58be893885c\.system_generated\steps\40\content.md"
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    json_start = content.find("[")
    if json_start == -1:
        print("No JSON found")
        return
        
    json_str = content[json_start:].strip()
    data = json.loads(json_str)
    
    # Known stablecoins and tokens without active USDT pairs on Binance Spot
    # (USDT, USDC, DAI, FDUSD, USDD, TUSD, USDE, USDS, EURC, USDG, etc.)
    stablecoins = {"USDT", "USDC", "DAI", "FDUSD", "USDD", "TUSD", "USDE", "USDS", "EURC", "USDG", "PYUSD", "USDTB", "BFUSD", "EUTBL", "USTB", "RLUSD", "USD1", "USDF", "USDM", "USYC", "JTRSY", "JAAA", "OUSD", "USX", "USDGO", "APXUSD", "U", "STABLE", "OUSG", "CC", "M", "FIGR_HELOC", "RAIN", "XAUT", "PAXG", "WLFI"}
    # Some tokens like LEO, TON, MNT might not be natively traded as USDT spot on Binance, but let's include major ones if they are. 
    # Usually TON is on Binance now. LEO is Bitfinex.
    # We'll just exclude known stablecoins and a few wrapped/fund tokens (STETH, WBTC, BUIDL, WSTETH, WEETH).
    exclude = stablecoins | {"STETH", "WBTC", "BUIDL", "WSTETH", "WEETH", "RETH", "CBETH", "BCAP", "Y", "A7A5"}
    
    valid_symbols = []
    for coin in data:
        sym = coin["symbol"].upper()
        if sym not in exclude:
            valid_symbols.append(sym + "/USDT")
        
        if len(valid_symbols) == 50:
            break
            
    print("Top 50:")
    print("[\n" + ",\n".join(f'    "{s}"' for s in valid_symbols) + "\n]")

if __name__ == "__main__":
    process()
