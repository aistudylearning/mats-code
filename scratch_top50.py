import json
import ccxt

def get_top_50_cmc_binance():
    # 1. Get the CMC (CoinGecko) list
    file_path = r"C:\Users\learning\.gemini\antigravity\brain\8e5fd336-c6a8-4d15-b0ed-c58be893885c\.system_generated\steps\40\content.md"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return
        
    json_start = content.find("[")
    if json_start == -1:
        print("No JSON found")
        return
        
    json_str = content[json_start:].strip()
    data = json.loads(json_str)
    
    # Exclude stablecoins and non-standard tokens
    stablecoins = {"USDT", "USDC", "DAI", "FDUSD", "USDD", "TUSD", "USDE", "USDS", "EURC", "USDG", "PYUSD", "USDTB", "BFUSD", "EUTBL", "USTB", "RLUSD", "USD1", "USDF", "USDM", "USYC", "JTRSY", "JAAA", "OUSD", "USX", "USDGO", "APXUSD", "U", "STABLE", "OUSG", "CC", "M", "FIGR_HELOC", "RAIN", "XAUT", "PAXG", "WLFI", "EURA", "AEUR"}
    exclude = stablecoins | {"STETH", "WBTC", "BUIDL", "WSTETH", "WEETH", "RETH", "CBETH", "BCAP", "Y", "A7A5"}
    
    cmc_symbols = []
    for coin in data:
        sym = coin["symbol"].upper()
        if sym not in exclude:
            cmc_symbols.append(sym + "/USDT")
            
    # 2. Get Binance active spot markets
    exchange = ccxt.binance()
    markets = exchange.load_markets()
    binance_usdt_spot = {m['symbol'] for m in markets.values() if m['quote'] == 'USDT' and m['type'] == 'spot' and m['active']}
    
    # 3. Filter CMC symbols that exist in Binance spot
    final_50 = []
    for sym in cmc_symbols:
        # ccxt might format symbols as SOL/USDT, etc. Let's check against binance_usdt_spot
        if sym in binance_usdt_spot:
            final_50.append(sym)
        if len(final_50) == 50:
            break
            
    print("[\n" + ",\n".join(f'    "{s}"' for s in final_50) + "\n]")

if __name__ == "__main__":
    get_top_50_cmc_binance()
