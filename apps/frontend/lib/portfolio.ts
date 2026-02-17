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

// Dashboard API Types
export type AllocationDashboardSummary = {
  allocation_type: string
  target_weight: string
  allocated_amount: string
  available_cash: string
  realized_pnl: string
  pnl_percentage: string
}

export type RecentTradeSummary = {
  id: string
  symbol: string
  side: string
  quantity: number
  executed_price: string | null
  executed_at: string | null
  realized_pnl: string | null
}

export type PortfolioDashboardResponse = {
  portfolio_id: string
  portfolio_name: string
  investment_amount: string  // Static initial capital
  available_cash: string  // Dynamic cash balance
  total_realized_pnl: string  // Accumulated realized P&L
  
  // NEW: Computed portfolio metrics (SEBI-compliant)
  total_position_value: string  // Sum of all position market values
  total_unrealized_pnl: string  // Sum of unrealized P&L from open positions
  current_portfolio_value: string  // available_cash + total_position_value (GROUND TRUTH)
  total_pnl: string  // realized_pnl + unrealized_pnl
  total_return_pct: string  // ((current_value - investment) / investment) * 100
  
  // Existing fields
  total_positions: number
  active_agents: number
  allocations: AllocationDashboardSummary[]
}

export type PortfolioAllocationSummary = {
  id: string
  portfolio_id: string
  allocation_type: string
  target_weight: string
  current_weight: string
  allocated_amount: string
  current_value: string
  expected_return: string | null
  expected_risk: string | null
  regime: string | null
  pnl: string
  pnl_percentage: string
  drift_percentage: string
  requires_rebalancing: boolean
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
  trading_agent: {
    id: string
    portfolio_id: string | null
    portfolio_allocation_id: string
    agent_type: string
    agent_name: string
    status: string
    strategy_config: Record<string, unknown> | null
    performance_metrics: Record<string, unknown> | null
    last_executed_at: string | null
    error_count: number
    last_error_message: string | null
    metadata: Record<string, unknown> | null
    created_at: string
    updated_at: string
  } | null
}

export type PortfolioAllocationListResponse = {
  items: PortfolioAllocationSummary[]
  total: number
}

type ApiError = {
  detail?: string
  message?: string
  error?: string
}

const PORTFOLIO_BASE_URL =
  process.env.NEXT_PUBLIC_PORTFOLIO_API_URL ?? "http://localhost:8000"

function getClientCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  const cookieString = document.cookie
  if (!cookieString) return null
  const entry = cookieString
    .split(";")
    .map((section) => section.trim())
    .find((section) => section.startsWith(`${name}=`))
  if (!entry) return null
  const [, value] = entry.split("=")
  return value ? decodeURIComponent(value) : null
}

function resolveAccessToken(explicitToken?: string): string {
  if (explicitToken) return explicitToken
  if (typeof window !== "undefined") {
    const cookieToken = getClientCookie("access_token")
    if (cookieToken) return cookieToken
    const stored = localStorage.getItem("access_token")
    if (stored) return stored
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
    let message =
      error.detail ||
      error.message ||
      error.error ||
      (typeof body === "string" ? body : undefined) ||
      response.statusText

    // If message is still not found and body is an object, try to stringify it properly
    if (!message && body && typeof body === "object") {
      try {
        // Try to extract any string property from the error object
        const bodyObj = body as Record<string, unknown>
        const possibleMessages = [
          bodyObj.detail,
          bodyObj.message,
          bodyObj.error,
          bodyObj.msg,
          bodyObj.description,
        ].filter((m): m is string => typeof m === "string")
        
        if (possibleMessages.length > 0) {
          message = possibleMessages[0]
        } else {
          // Last resort: stringify the object, but limit length
          const stringified = JSON.stringify(body)
          message = stringified.length > 200 ? stringified.substring(0, 200) + "..." : stringified
        }
      } catch {
        // If stringification fails, use status text
        message = response.statusText
      }
    }

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
  search?: string,
  profitability?: string,
  sortBy: string = "updatedAt",
  sortOrder: "asc" | "desc" = "desc",
  accessToken?: string,
): Promise<PositionsResponse> {
  const token = resolveAccessToken(accessToken)

  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
    sortBy,
    sortOrder,
  })
  
  if (search) {
    params.append("search", search)
  }
  
  if (profitability) {
    params.append("profitability", profitability)
  }

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
  symbol?: string,
  side?: string,
  orderType?: string,
  status?: string,
  agentId?: string,
  accessToken?: string,
): Promise<RecentTradesResponse> {
  const token = resolveAccessToken(accessToken)

  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  })
  
  if (symbol) params.append("symbol", symbol)
  if (side) params.append("side", side)
  if (orderType) params.append("orderType", orderType)
  if (status) params.append("status", status)
  if (agentId) params.append("agent_id", agentId)

  return request<RecentTradesResponse>(`/api/portfolio/recent-trades?${params}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function getPortfolioDashboard(
  accessToken?: string,
): Promise<PortfolioDashboardResponse> {
  const token = resolveAccessToken(accessToken)

  return request<PortfolioDashboardResponse>("/api/portfolio/dashboard", {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function getPortfolioAllocations(
  accessToken?: string,
): Promise<PortfolioAllocationListResponse> {
  const token = resolveAccessToken(accessToken)

  return request<PortfolioAllocationListResponse>("/api/portfolio/allocations", {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export type TradeRequest = {
  portfolio_id: string
  symbol: string
  exchange?: string
  segment?: string
  side: "BUY" | "SELL"
  order_type: "market" | "limit" | "stop" | "stop_loss" | "take_profit"
  quantity: number
  limit_price?: number
  trigger_price?: number
  trade_type?: string
  customer_id?: string
  source?: string
  metadata?: Record<string, unknown>
  allocation_id?: string
}

export type TradeResponse = {
  success: boolean
  message: string
  trades: Array<{
    id: string
    symbol: string
    side: string
    order_type: string
    status: string
    quantity: number
    price?: string
    executed_quantity?: number
    executed_price?: string
    execution_time?: string
  }>
  pending_orders: number
  portfolio: {
    id: string
    current_value: string
    updated_at: string
  }
}

export async function submitTrade(
  tradeData: TradeRequest,
  accessToken?: string,
): Promise<TradeResponse> {
  const token = resolveAccessToken(accessToken)

  // Ensure quantity is a positive integer
  const quantity = Math.floor(tradeData.quantity)
  if (!Number.isInteger(quantity) || quantity <= 0) {
    throw new Error("Quantity must be a positive integer")
  }

  // Clean up the request data to match backend expectations
  const cleanedData: Record<string, unknown> = {
    portfolio_id: tradeData.portfolio_id,
    symbol: tradeData.symbol,
    side: tradeData.side,
    order_type: tradeData.order_type,
    quantity: quantity,
  }

  // Add optional fields only if they have values
  if (tradeData.exchange) {
    cleanedData.exchange = tradeData.exchange
  }
  if (tradeData.segment) {
    cleanedData.segment = tradeData.segment
  }
  if (tradeData.trade_type) {
    cleanedData.trade_type = tradeData.trade_type
  }
  if (tradeData.customer_id) {
    cleanedData.customer_id = tradeData.customer_id
  }
  if (tradeData.source) {
    cleanedData.source = tradeData.source
  }
  if (tradeData.metadata) {
    cleanedData.metadata = tradeData.metadata
  }
  if (tradeData.allocation_id) {
    cleanedData.allocation_id = tradeData.allocation_id
  }

  // Handle price fields based on order type
  // For market orders, explicitly omit limit_price and trigger_price
  // For limit orders, require limit_price
  // For stop orders, require trigger_price
  if (tradeData.order_type === "market") {
    // Market orders should not have limit_price or trigger_price
    // They are already omitted by not adding them to cleanedData
  } else if (tradeData.order_type === "limit") {
    if (tradeData.limit_price !== undefined && tradeData.limit_price !== null && tradeData.limit_price > 0) {
      cleanedData.limit_price = tradeData.limit_price
    } else {
      throw new Error("Limit price is required for limit orders and must be greater than 0")
    }
  } else if (["stop", "stop_loss", "take_profit"].includes(tradeData.order_type)) {
    if (tradeData.trigger_price !== undefined && tradeData.trigger_price !== null && tradeData.trigger_price > 0) {
      cleanedData.trigger_price = tradeData.trigger_price
    } else {
      throw new Error("Trigger price is required for stop/take-profit orders and must be greater than 0")
    }
    // Limit price is optional for stop orders
    if (tradeData.limit_price !== undefined && tradeData.limit_price !== null && tradeData.limit_price > 0) {
      cleanedData.limit_price = tradeData.limit_price
    }
  }

  return request<TradeResponse>("/api/trades/", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(cleanedData),
  })
}
