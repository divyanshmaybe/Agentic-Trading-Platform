/**
 * Admin Dashboard API Types and Client
 */

import { apiClient } from "./api"
import { formatCurrency } from "./dashboardData"

// Base response types
export interface OrganizationSummary {
  organization_id: string
  total_portfolios: number
  active_portfolios: number
  total_users: number
  active_users: number
  total_aum: number
  total_available_cash: number
  total_invested: number
}

export interface FinancialMetrics {
  total_realized_pnl: number
  total_unrealized_pnl: number
  total_pnl: number
  overall_roi_percentage: number
  best_performing_portfolio_id: string
  best_performing_portfolio_pnl: number
  worst_performing_portfolio_id: string
  worst_performing_portfolio_pnl: number
}

export interface MonthlyPnl {
  month: string
  realized_pnl: number
  cumulative_pnl: number
  trade_count: number
}

export interface DailyPnl {
  date: string
  realized_pnl: number
  trade_count: number
}

export interface TradingMetrics {
  total_trades: number
  trades_today: number
  trades_this_week: number
  trades_this_month: number
  total_volume: number
  successful_trades: number
  failed_trades: number
  pending_trades: number
  success_rate_percentage: number
  avg_trade_size: number
  total_fees: number
  total_taxes: number
}

export interface TradesByStatus {
  executed: number
  pending: number
  pending_tp: number
  pending_sl: number
  cancelled: number
  failed: number
}

export interface TradesBySide {
  buy: number
  sell: number
  short_sell: number
  cover: number
}

export interface HourlyDistribution {
  hour: number
  trade_count: number
  volume: number
}

export interface TradeVolume {
  date: string
  trade_count: number
  buy_count: number
  sell_count: number
  total_volume: number
}

export interface AgentMetrics {
  agent_type: string
  agent_count: number
  active_agents: number
  error_agents: number
  total_realized_pnl: number
  total_trades: number
  successful_trades: number
  win_rate_percentage: number
  avg_pnl_per_trade: number
  total_positions: number
  open_positions: number
}

export interface AgentSummary {
  agent_id: string
  agent_name: string
  agent_type: string
  portfolio_id: string
  realized_pnl: number
  trade_count: number
  win_rate: number
  status: string
}

export interface AgentSnapshot {
  snapshot_at: string
  agent_type: string
  realized_pnl: number
  current_value: number
}

export interface UserPortfolio {
  user_id: string
  portfolio_id: string
  portfolio_name: string
  investment_amount: number
  current_value: number
  available_cash: number
  realized_pnl: number
  roi_percentage: number
  total_trades: number
  open_positions: number
  status: "profit" | "loss" | "breakeven"
  last_trade_at: string | null
  created_at: string
}

export interface PnlBucket {
  range_label: string
  range_min: number
  range_max: number
  user_count: number
  total_pnl: number
}

export interface PositionMetrics {
  total_positions: number
  open_positions: number
  closed_positions: number
  long_positions: number
  short_positions: number
  total_invested_in_positions: number
}

export interface SymbolConcentration {
  symbol: string
  total_quantity: number
  total_value: number
  position_count: number
  percentage_of_total: number
}

export interface PendingOrders {
  pending_limit_orders: number
  pending_stop_loss: number
  pending_take_profit: number
  pending_auto_sell: number
  total_pending_value: number
}

export interface PipelineMetrics {
  signals_today: number
  signals_this_week: number
  avg_llm_delay_ms: number | null
  avg_trade_delay_ms: number | null
  min_llm_delay_ms: number | null
  max_llm_delay_ms: number | null
  min_trade_delay_ms: number | null
  max_trade_delay_ms: number | null
}

export interface ExecutionMetrics {
  total_executions: number
  successful_executions: number
  failed_executions: number
  pending_executions: number
  avg_execution_time_ms: number | null
}

export interface PortfolioSnapshot {
  snapshot_at: string
  total_value: number
  realized_pnl: number
  unrealized_pnl: number
}

export interface AlphaMetrics {
  total_runs: number
  completed_runs: number
  running_runs: number
  failed_runs: number
  live_alphas_count: number
  running_alphas: number
  total_alpha_signals: number
  executed_signals: number
  pending_signals: number
}

export interface AdminDashboardResponse {
  generated_at: string
  organization_id: string
  data_freshness: string
  organization_summary: OrganizationSummary
  financial_metrics: FinancialMetrics
  monthly_pnl_series: MonthlyPnl[]
  daily_pnl_series: DailyPnl[]
  trading_metrics: TradingMetrics
  trades_by_status: TradesByStatus
  trades_by_side: TradesBySide
  hourly_trade_distribution: HourlyDistribution[]
  trade_volume_series: TradeVolume[]
  agent_metrics_by_type: AgentMetrics[]
  top_agents: AgentSummary[]
  bottom_agents: AgentSummary[]
  agent_pnl_series: AgentSnapshot[]
  user_portfolio_metrics: UserPortfolio[]
  user_pnl_distribution: PnlBucket[]
  top_bottom_users: {
    top_users: UserPortfolio[]
    bottom_users: UserPortfolio[]
  }
  position_metrics: PositionMetrics
  symbol_concentration: SymbolConcentration[]
  pending_orders: PendingOrders
  pipeline_metrics: PipelineMetrics
  execution_metrics: ExecutionMetrics
  portfolio_value_series: PortfolioSnapshot[]
  alpha_metrics: AlphaMetrics
}

export interface AdminSummaryResponse {
  generated_at: string
  organization_id: string
  total_portfolios: number
  active_portfolios: number
  total_aum: number
  total_realized_pnl: number
  overall_roi_percentage: number
  portfolios_in_loss: number
  agents_with_errors: number
  pending_orders_count: number
  trades_today: number
  signals_today: number
  high_concentration_symbols: string[]
}

// API Client Functions
export async function getAdminDashboard(): Promise<AdminDashboardResponse> {
  return apiClient.get<AdminDashboardResponse>("/api/admin/dashboard")
}

export async function getAdminSummary(): Promise<AdminSummaryResponse> {
  return apiClient.get<AdminSummaryResponse>("/api/admin/summary")
}

// Utility Functions
export interface Position {
  symbol: string
  quantity: number
  average_buy_price: number
  current_price?: number
}

export interface Portfolio {
  available_cash: number
  positions: Position[]
}

/**
 * Calculate unrealized P&L for positions
 * Note: Requires current market prices - placeholder for now
 */
export function calculateUnrealizedPnl(
  positions: Position[],
  currentPrices: Record<string, number> = {}
): number {
  return positions.reduce((total, position) => {
    const currentPrice = currentPrices[position.symbol] || position.current_price || 0
    if (!currentPrice || !position.average_buy_price) return total
    const unrealizedPnl = (currentPrice - position.average_buy_price) * position.quantity
    return total + unrealizedPnl
  }, 0)
}

/**
 * Calculate current portfolio value (cash + positions at current prices)
 */
export function calculateCurrentPortfolioValue(
  portfolio: Portfolio,
  currentPrices: Record<string, number> = {}
): number {
  const positionsValue = portfolio.positions.reduce((total, position) => {
    const currentPrice = currentPrices[position.symbol] || position.current_price || 0
    return total + currentPrice * position.quantity
  }, 0)
  return portfolio.available_cash + positionsValue
}

/**
 * Get current price for a symbol (placeholder - to be integrated with live price feed)
 */
export function getCurrentPrice(symbol: string): Promise<number> {
  // TODO: Integrate with live price fetching API
  return Promise.resolve(0)
}

// Re-export formatCurrency for convenience
export { formatCurrency }

// Export computeRoiPct for reuse
export function computeRoiPct(series: number[]): number {
  if (series.length < 2) return 0
  const first = series[0]
  const last = series[series.length - 1]
  if (first === 0) return 0
  return ((last - first) / first) * 100
}

