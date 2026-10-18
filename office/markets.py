"""
The desk's market universe: every market the strategy lab tests and the hourly watch scans.

Each entry: (history ticker, Capital.com epic, asset class). History comes from Yahoo (free, up to 730 days of
hourly bars); orders go to Capital.com (DEMO). All 37 epics were checked against the demo account on
2026-10-18 (US Russell 2000 is not offered there). Prefix "yf:" marks a Yahoo ticker that has no . ^ = -
in it (plain US share tickers), so the data loader knows to use Yahoo rather than Capital.
"""

UNIVERSE = [
    # currencies (trade 24 hours, Sunday evening to Friday evening)
    ("EURUSD=X", "EURUSD", "fx"), ("GBPUSD=X", "GBPUSD", "fx"), ("USDJPY=X", "USDJPY", "fx"), ("AUDUSD=X", "AUDUSD", "fx"),
    ("USDCAD=X", "USDCAD", "fx"), ("USDCHF=X", "USDCHF", "fx"), ("NZDUSD=X", "NZDUSD", "fx"), ("EURGBP=X", "EURGBP", "fx"),
    ("EURJPY=X", "EURJPY", "fx"), ("GBPJPY=X", "GBPJPY", "fx"),
    # stock indices
    ("ES=F", "US500", "index"), ("NQ=F", "US100", "index"), ("YM=F", "US30", "index"), ("^FTSE", "UK100", "index"),
    ("^GDAXI", "DE40", "index"), ("^N225", "J225", "index"), ("^FCHI", "FR40", "index"), ("^STOXX50E", "EU50", "index"),
    # commodities
    ("GC=F", "GOLD", "commodity"), ("SI=F", "SILVER", "commodity"), ("CL=F", "OIL_CRUDE", "commodity"),
    ("NG=F", "NATURALGAS", "commodity"), ("HG=F", "COPPER", "commodity"),
    # crypto (trades every day, including weekends)
    ("BTC-USD", "BTCUSD", "crypto"), ("ETH-USD", "ETHUSD", "crypto"), ("SOL-USD", "SOLUSD", "crypto"),
    ("XRP-USD", "XRPUSD", "crypto"), ("ADA-USD", "ADAUSD", "crypto"), ("LTC-USD", "LTCUSD", "crypto"),
    # shares
    ("yf:AAPL", "AAPL", "stock"), ("yf:NVDA", "NVDA", "stock"), ("yf:MSFT", "MSFT", "stock"), ("yf:TSLA", "TSLA", "stock"),
    ("yf:AMZN", "AMZN", "stock"), ("yf:META", "META", "stock"), ("yf:GOOGL", "GOOGL", "stock"), ("VOD.L", "VODL", "stock"),
]

# exits by asset class: (stop %, target %, time-stop in hourly bars). Every target is 2x its stop (desk minimum 1.5).
EXITS = {"fx": (0.35, 0.7, 12), "index": (0.8, 1.6, 12), "commodity": (1.0, 2.0, 12), "crypto": (2.0, 4.0, 12), "stock": (1.5, 3.0, 12)}

FAMILY_SHORT = {"sma_cross": "sma", "breakout": "breakout", "macd": "macd", "rsi_fade": "rsifade", "williams": "williams"}


def asset_class(epic: str) -> str:
    return next((c for _, e, c in UNIVERSE if e == epic.upper()), "other")


def strategy_name(epic: str, family: str) -> str:
    return f"{epic.lower()}-h1-{FAMILY_SHORT.get(family, family.replace('_', ''))}"
