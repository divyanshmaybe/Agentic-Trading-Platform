export type NotificationAction = {
  label: string
  value: string
}

export type NotificationItem = {
  id: string
  title: string
  body: string
  timestamp: string
  actions?: NotificationAction[]
}

export type PortfolioAllocation = {
  label: string
  value: number
}

export type PortfolioSummary = {
  portfolioName: string
  // NEW: Use backend-calculated values
  currentValue: number  // From backend: current_portfolio_value
  totalUnrealizedPnl: number  // From backend: total_unrealized_pnl
  totalPnl: number  // From backend: total_pnl
  totalReturnPct: number  // From backend: total_return_pct
  // Existing fields
  investmentAmount: number
  availableCash: number
  changePct: number  // Deprecated, use totalReturnPct instead
  changeValue: number  // Deprecated, use totalPnl instead
  dailyPnL: number  // Deprecated, use totalPnl instead
  riskTolerance: string
  expectedReturn: number
  investmentHorizon: number
  liquidityNeeds: string
  allocation: PortfolioAllocation[]
}

export type StockItem = {
  symbol: string
  name: string
  changePct: number
  prices: number[]
  pricesError?: boolean
}

export type NewsItem = {
  id: string
  headline: string
  publisher: string
  timestamp: string
  summary: string
}

