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
  totalValue: number
  investmentAmount: number
  changePct: number
  changeValue: number
  dailyPnL: number
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
}

export type NewsItem = {
  id: string
  headline: string
  publisher: string
  timestamp: string
  summary: string
}

