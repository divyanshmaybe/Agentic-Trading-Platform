import type { NewsItem, NotificationItem, PortfolioSummary, StockItem } from "@/lib/dashboardTypes"

export const notificationItems: NotificationItem[] = [
  {
    id: "notif-1",
    title: "AI Trade Execution Required",
    body: "AI detected Fed rate pivot signals in macro news. Recommends rotating 15% into defensive utilities. Approve execution?",
    timestamp: "2 min ago",
    actions: [
      { label: "Yes", value: "yes" },
      { label: "No", value: "no" },
    ],
  },
  {
    id: "notif-2",
    title: "AI Executed Trade",
    body: "AI auto-executed: Bought 2.4k shares AAPL at $178.32 based on earnings sentiment surge (+94% positive signals).",
    timestamp: "8 min ago",
  },
  {
    id: "notif-3",
    title: "AI Alpha Signal Generated",
    body: "AI identified 3 high-conviction alpha opportunities in energy sector. Expected return: +8.2% over 30 days. Review signals?",
    timestamp: "15 min ago",
    actions: [
      { label: "Yes", value: "yes" },
      { label: "No", value: "no" },
    ],
  },
  {
    id: "notif-4",
    title: "AI News Reaction",
    body: "AI processed Fed minutes release: Detected hawkish tilt. Auto-hedging treasury positions with 200 TLT puts at $92.50.",
    timestamp: "28 min ago",
  },
  {
    id: "notif-5",
    title: "AI Risk Alert",
    body: "AI flagged correlation breakdown in crypto momentum basket. Volatility spike detected. Approve risk reduction?",
    timestamp: "42 min ago",
    actions: [
      { label: "Yes", value: "yes" },
      { label: "No", value: "no" },
    ],
  },
  {
    id: "notif-6",
    title: "AI Generated Alpha",
    body: "Smart sentiment model identified mean-reversion opportunity: TSLA oversold by 2.3σ vs 90-day baseline. Entry suggested at $242.",
    timestamp: "1 hr 5 min ago",
  },
  {
    id: "notif-7",
    title: "AI Trade Alert",
    body: "AI executed pairs trade: Long NVDA / Short AMD based on relative strength divergence. Net exposure: $480k.",
    timestamp: "1 hr 30 min ago",
  },
  {
    id: "notif-8",
    title: "AI Rebalance Suggestion",
    body: "AI analyzed sector rotation news. Recommends shifting 12% from tech to healthcare. Approve rebalance?",
    timestamp: "2 hr 15 min ago",
    actions: [
      { label: "Yes", value: "yes" },
      { label: "No", value: "no" },
    ],
  },
]

export const portfolioSummary: PortfolioSummary = {
  portfolioName: "Managed Portfolio",
  currentValue: 1245000,
  totalUnrealizedPnl: 22840,
  totalPnl: 45000,
  totalReturnPct: 3.75,
  investmentAmount: 1200000,
  availableCash: 50000,
  changePct: 1.86,
  changeValue: 22840,
  dailyPnL: 14280,
  riskTolerance: "moderate",
  expectedReturn: 8.0,
  investmentHorizon: 3,
  liquidityNeeds: "standard",
  allocation: [
    { label: "Long-Term Strategies", value: 45 },
    { label: "Intraday Strategies", value: 32 },
    { label: "High-Risk", value: 23 },
  ],
}

export const stocks: StockItem[] = [
  {
    symbol: "ALP",
    name: "Alpha Core Holdings",
    changePct: 2.14,
    prices: [102, 104, 103.5, 106, 107.2, 108, 110],
  },
  {
    symbol: "LRF",
    name: "Low Risk Fund",
    changePct: 0.88,
    prices: [89.5, 89.9, 90.1, 90.6, 90.9, 91.2, 91.8],
  },
  {
    symbol: "HRS",
    name: "High-Risk Strategies",
    changePct: -1.27,
    prices: [58.2, 57.6, 59.1, 58.7, 58.9, 57.8, 57.2],
  },
  {
    symbol: "CRY",
    name: "Crypto Momentum",
    changePct: 4.63,
    prices: [32.5, 33.6, 33.9, 34.8, 35.6, 36.2, 37.1],
  },
]

export const newsFeedItems: NewsItem[] = [
  {
    id: "news-1",
    headline: "AI Hedge Funds Double Down on Defensive Plays",
    publisher: "QuantWire",
    timestamp: "Just now",
    summary: "Systematic managers rotate into utilities while keeping leveraged tech hedges active amid volatility compression signals.",
  },
  {
    id: "news-2",
    headline: "Macro Desk Targets Post-Fed Relief Rally",
    publisher: "StreetPulse",
    timestamp: "5 min ago",
    summary: "Traders float strategy to extend duration on sovereign debt with selective growth bets as rate pause narrative gains traction.",
  },
  {
    id: "news-3",
    headline: "Commodity Surge Sparks Rebalance Alerts",
    publisher: "GlobalComms",
    timestamp: "18 min ago",
    summary: "Smart beta portfolios triggered auto-rebalancing after energy complex rallied 2.4% on unexpected inventory drawdowns.",
  },
  {
    id: "news-4",
    headline: "Desk Liquidity Models Flag Yen Carry Wobble",
    publisher: "FXScope",
    timestamp: "32 min ago",
    summary: "Overnight cross-currency spreads widened 11 bps, prompting automated hedge overlays across the G10 carry sleeve.",
  },
  {
    id: "news-5",
    headline: "Vol Control Funds Rebalance Into Green Energy",
    publisher: "EnergyQuant",
    timestamp: "46 min ago",
    summary: "Carbon-linked ETNs outperformed and triggered systematic inflows as realized volatility compressed within target bands.",
  },
  {
    id: "news-6",
    headline: "Rates Traders Fade Front-End Hike Bets",
    publisher: "MacroSignal",
    timestamp: "1 hr 5 min ago",
    summary: "Swap desks unwind hawkish Eurodollar positioning after CPI print undershoots consensus for the second month.",
  },
  {
    id: "news-7",
    headline: "Crypto Basis Narrows Ahead of ETF Vote",
    publisher: "ChainBeat",
    timestamp: "1 hr 40 min ago",
    summary: "Funding rates normalize as spot-futures basis compresses, with arbitrage desks rotating collateral into short-term treasuries.",
  },
  {
    id: "news-8",
    headline: "European Utilities Bounce On Policy Clarity",
    publisher: "EuroWire",
    timestamp: "2 hr 12 min ago",
    summary: "Commission guidance eases price-cap fears, driving sector rally and sparking cross-asset rotation signals.",
  },
]
