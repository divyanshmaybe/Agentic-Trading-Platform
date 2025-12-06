export type AgentType = "high_risk" | "low_risk" | "liquid" | "alpha"

export type AgentStatus = "active" | "paused" | "stopped" | "error"

export interface AgentAllocation {
  id: string
  portfolio_id: string
  allocation_type: string
  target_weight: string
  current_weight: string
  allocated_amount: string
  available_cash: string
  expected_return: string
  expected_risk: string
  regime: string
  pnl: string
  pnl_percentage: string
  drift_percentage: string
  requires_rebalancing: boolean
  metadata: Record<string, any>
  created_at: string
  updated_at: string
  trading_agent: TradingAgent | null
}

export interface TradingAgent {
  id: string
  portfolio_id: string
  portfolio_allocation_id: string
  agent_type: string
  agent_name: string
  status: AgentStatus
  strategy_config: Record<string, any>
  performance_metrics: Record<string, any> | null
  last_executed_at: string
  error_count: number
  last_error_message: string | null
  metadata: Record<string, any>
  created_at: string
  updated_at: string
}

export interface AgentPosition {
  id: string
  portfolio_id: string
  symbol: string
  exchange: string
  segment: string
  quantity: number
  average_buy_price: string
  realized_pnl: string
  position_type: string
  status: string
  updated_at: string
}

export interface AgentTrade {
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
  llm_delay?: string
  trade_delay?: string
  agent_id?: string
  agent_name?: string
  triggered_by?: string
}

export interface AgentDashboard {
  agent_id: string
  agent_name: string
  agent_type: AgentType
  portfolio_id: string
  status: AgentStatus
  realized_pnl: string
  positions_count: number
  positions: AgentPosition[]
  allocation: AgentAllocation
  performance_metrics: Record<string, any> | null
  recent_trades: AgentTrade[]
}

