import pathway as pw


class MarketData(pw.Schema):
    symbol: str
    date: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
