export type AlphaStat = {
  label: string
  value: string
  helper?: string
}

export type TopAlpha = {
  id: string
  name: string
  returnPct: number
  direction: "up" | "down"
}

export type AlphaSeriesPoint = {
  time: string
  bullish: number
  bearish: number
}

export type TradeHistoryItem = {
  id: string
  time: string
  alphaName: string
  entryPrice: number
  exitPrice: number
  profitLossPct: number
  tradeType: "Long" | "Short"
}

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  time: string
}

export const alphaStats: AlphaStat[] = [
  { label: "Total Investment", value: "₹2.4 Cr", helper: "+6.2% since last week" },
  { label: "Current Returns", value: "18.4%", helper: "Trailing 30 days" },
  { label: "Win Ratio", value: "63%", helper: "Across active alphas" },
  { label: "Total Alphas Running", value: "24", helper: "8 paused" },
  { label: "Total Trades", value: "1,284", helper: "Includes paper trades" },
]

export const topAlphas: TopAlpha[] = [
  { id: "alpha-1", name: "(RSI < 30) && (MACD > 0)", returnPct: 12.4, direction: "up" },
  { id: "alpha-2", name: "VWAP cross + Volume Surge", returnPct: 10.1, direction: "up" },
  { id: "alpha-3", name: "Heikin Ashi Momentum Fade", returnPct: -4.3, direction: "down" },
  { id: "alpha-4", name: "Mean Reversion (Bollinger -2σ)", returnPct: 8.9, direction: "up" },
  { id: "alpha-5", name: "52W High Breakout + OBV", returnPct: 6.8, direction: "up" },
  { id: "alpha-6", name: "Short Squeeze Detector", returnPct: 3.1, direction: "up" },
  { id: "alpha-7", name: "Gap Fade Intraday", returnPct: -2.1, direction: "down" },
  { id: "alpha-8", name: "ATR Expansion Trend Ride", returnPct: 5.6, direction: "up" },
  { id: "alpha-9", name: "Fibonacci Pullback Long", returnPct: 4.2, direction: "up" },
  { id: "alpha-10", name: "High Beta Pair Hedge", returnPct: 1.3, direction: "up" },
]

export const alphaSeries: AlphaSeriesPoint[] = [
  { time: "09:30", bullish: 0.4, bearish: -0.3 },
  { time: "10:00", bullish: 0.9, bearish: -0.5 },
  { time: "10:30", bullish: 1.5, bearish: -0.8 },
  { time: "11:00", bullish: 2.3, bearish: -1.1 },
  { time: "11:30", bullish: 2.9, bearish: -1.4 },
  { time: "12:00", bullish: 1.6, bearish: -1.6 },
  { time: "12:30", bullish: 0.8, bearish: -1.6 },
  { time: "13:00", bullish: 0.4, bearish: -1.8 },
  { time: "13:30", bullish: 0.2, bearish: -2.1 },
  { time: "14:00", bullish: 0.1, bearish: -2.5 },
  { time: "14:30", bullish: 0.05, bearish: -2.9 },
  { time: "15:00", bullish: 0.02, bearish: -3.3 },
]

export const tradeHistory: TradeHistoryItem[] = [
  {
    id: "trade-1",
    time: "09:45 AM",
    alphaName: "VWAP cross + Volume Surge",
    entryPrice: 182.45,
    exitPrice: 188.72,
    profitLossPct: 3.44,
    tradeType: "Long",
  },
  {
    id: "trade-2",
    time: "10:18 AM",
    alphaName: "Gap Fade Intraday",
    entryPrice: 94.32,
    exitPrice: 91.28,
    profitLossPct: -3.22,
    tradeType: "Short",
  },
  {
    id: "trade-3",
    time: "11:12 AM",
    alphaName: "Mean Reversion (Bollinger -2σ)",
    entryPrice: 256.91,
    exitPrice: 265.14,
    profitLossPct: 3.21,
    tradeType: "Long",
  },
  {
    id: "trade-4",
    time: "12:37 PM",
    alphaName: "Short Squeeze Detector",
    entryPrice: 141.05,
    exitPrice: 147.89,
    profitLossPct: 4.85,
    tradeType: "Long",
  },
  {
    id: "trade-5",
    time: "01:24 PM",
    alphaName: "ATR Expansion Trend Ride",
    entryPrice: 73.4,
    exitPrice: 70.81,
    profitLossPct: -3.54,
    tradeType: "Short",
  },
  {
    id: "trade-6",
    time: "02:16 PM",
    alphaName: "Fibonacci Pullback Long",
    entryPrice: 318.62,
    exitPrice: 327.88,
    profitLossPct: 2.9,
    tradeType: "Long",
  },
]

export const chatMessages: ChatMessage[] = [
  {
    id: "msg-1",
    role: "assistant",
    content: "👋 Hey! Share the asset or regime you're targeting and I can suggest alpha ideas.",
    time: "09:35",
  },
  {
    id: "msg-2",
    role: "user",
    content: "Need a mean reversion alpha for NIFTY intraday. Prefer mid-volatility names.",
    time: "09:36",
  },
  {
    id: "msg-3",
    role: "assistant",
    content:
      "Try combining Bollinger Band extreme with RSI divergence. Layer in volume squeeze to filter chop.",
    time: "09:36",
  },
  {
    id: "msg-4",
    role: "user",
    content: "Can you tweak it to exit on VWAP reversion or time stop?",
    time: "09:38",
  },
  {
    id: "msg-5",
    role: "assistant",
    content:
      "Absolutely. Use VWAP cross as soft exit with hard stop = entry ±1.2×ATR. Add time stop at 45 mins.",
    time: "09:39",
  },
]

export const alphaPagination = {
  pageSize: 4,
}


