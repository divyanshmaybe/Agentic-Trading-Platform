// Portfolio API Types
export type Portfolio = {
  id: string
  organization_id: string
  customer_id: string
  portfolio_name: string
  investment_amount: string
  current_value: string
  investment_horizon_years: number
  expected_return_target: string
  risk_tolerance: string
  liquidity_needs: string
  rebalancing_frequency: string | null
  allocation_strategy: string | null
  metadata: {
    auto_created?: boolean
    created_for_user?: string
  }
}

export type Position = {
  id: string
  portfolio_id: string
  symbol: string
  exchange: string
  segment: string
  quantity: number
  average_buy_price: string
  current_price: string
  current_value: string
  pnl: string
  pnl_percentage: string
  position_type: string
  status: string
  updated_at: string
}

export type PositionsResponse = {
  items: Position[]
  page: number
  limit: number
  total: number
}

export type Quote = {
  symbol: string
  price: string
  provider: string
  source: string
}

export type QuotesResponse = {
  data: Quote[]
  count: number
  requested_at: string
  missing: string[] | null
}

export type CandleData = {
  timestamp: string
  open: string
  high: string
  low: string
  close: string
  volume: string
}

export type MarketCandlesResponse = {
  data: Quote[]
  count: number
  requested_at: string
  missing: string[] | null
  metadata?: {
    candles?: Record<string, CandleData[]>
  }
}

export type Trade = {
  id: string
  portfolio_id: string
  symbol: string
  side: string
  order_type: string
  quantity: number
  executed_quantity: number
  executed_price: string
  status: string
  net_amount: string
  trade_type: string
  created_at: string
  execution_time: string
}

export type RecentTradesResponse = {
  items: Trade[]
  page: number
  limit: number
  total: number
}

type ApiError = {
  detail?: string
  message?: string
  error?: string
}

const PORTFOLIO_BASE_URL =
  process.env.NEXT_PUBLIC_PORTFOLIO_API_URL ?? "http://localhost:8000"

function resolveAccessToken(explicitToken?: string): string {
  if (explicitToken) return explicitToken
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token")
    if (token) return token
  }
  throw new Error("Missing access token. Please log in again.")
}

async function request<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(`${PORTFOLIO_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  })

  const isJson = response.headers
    .get("content-type")
    ?.includes("application/json")

  const body = isJson ? await response.json() : null

  if (!response.ok) {
    const error: ApiError = body ?? {}
    const message =
      error.detail ||
      error.message ||
      error.error ||
      (typeof body === "string" ? body : undefined) ||
      response.statusText

    // If unauthorized, clear token and redirect to login
    if (response.status === 401) {
      if (typeof window !== "undefined") {
        localStorage.removeItem("access_token")
        localStorage.removeItem("refresh_token")
        window.location.href = "/login"
      }
    }

    throw new Error(message || "Request failed")
  }

  return body as T
}

export async function getPortfolio(accessToken?: string): Promise<Portfolio> {
  const token = resolveAccessToken(accessToken)

  return request<Portfolio>("/api/portfolio/", {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function getPositions(
  page = 1,
  limit = 10,
  accessToken?: string,
): Promise<PositionsResponse> {
  const token = resolveAccessToken(accessToken)

  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  })

  return request<PositionsResponse>(`/api/portfolio/positions?${params}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function fetchQuotes(
  symbols: string[],
  accessToken?: string,
): Promise<QuotesResponse> {
  const token = resolveAccessToken(accessToken)

  const params = new URLSearchParams()
  symbols.forEach((symbol) => params.append("symbols", symbol))

  return request<QuotesResponse>(`/api/market/quotes?${params}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function fetchMarketCandles(
  symbols: string[],
  period: string = "7d",
  accessToken?: string,
): Promise<MarketCandlesResponse> {
  const token = resolveAccessToken(accessToken)

  const params = new URLSearchParams()
  params.append("candle", period)
  symbols.forEach((symbol) => params.append("symbols", symbol))

  return request<MarketCandlesResponse>(`/api/market/quotes?${params}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function getRecentTrades(
  page = 1,
  limit = 10,
  accessToken?: string,
): Promise<RecentTradesResponse> {
  const token = resolveAccessToken(accessToken)

  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  })

  return request<RecentTradesResponse>(`/api/portfolio/recent-trades?${params}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

