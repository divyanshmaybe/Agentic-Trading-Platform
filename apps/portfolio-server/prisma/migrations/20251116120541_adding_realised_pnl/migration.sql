-- CreateTable
CREATE TABLE "objectives" (
    "id" TEXT NOT NULL,
    "user_id" TEXT NOT NULL,
    "name" TEXT,
    "raw" JSONB DEFAULT '{}',
    "source" TEXT,
    "structured_payload" JSONB DEFAULT '{}',
    "investable_amount" DECIMAL(20,4),
    "investment_horizon_years" INTEGER,
    "investment_horizon_label" TEXT,
    "target_return" DECIMAL(9,6),
    "target_returns" JSONB DEFAULT '[]',
    "risk_tolerance" TEXT,
    "risk_aversion_lambda" DECIMAL(9,6),
    "liquidity_needs" TEXT,
    "rebalancing_frequency" TEXT,
    "constraints" JSONB DEFAULT '{}',
    "preferences" JSONB DEFAULT '{}',
    "generic_notes" JSONB DEFAULT '[]',
    "missing_fields" JSONB DEFAULT '[]',
    "completion_status" TEXT NOT NULL DEFAULT 'pending',
    "status" TEXT NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "objectives_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "portfolios" (
    "id" TEXT NOT NULL,
    "user_id" TEXT,
    "objective_id" TEXT,
    "organization_id" TEXT NOT NULL,
    "customer_id" TEXT NOT NULL,
    "portfolio_name" TEXT NOT NULL,
    "initial_investment" DECIMAL(20,4) NOT NULL,
    "investment_amount" DECIMAL(20,4) NOT NULL,
    "current_value" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "investment_horizon_years" INTEGER NOT NULL,
    "expected_return_target" DECIMAL(7,4) NOT NULL,
    "risk_tolerance" TEXT NOT NULL,
    "liquidity_needs" TEXT NOT NULL,
    "rebalancing_frequency" JSONB,
    "allocation_strategy" JSONB,
    "constraints" JSONB,
    "status" TEXT NOT NULL DEFAULT 'active',
    "allocation_status" TEXT NOT NULL DEFAULT 'pending',
    "rebalancing_date" TIMESTAMP(3),
    "last_rebalanced_at" TIMESTAMP(3),
    "next_rebalance_at" TIMESTAMP(3),
    "allocation_trades" JSONB,
    "realized_pnl" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,
    "deleted_at" TIMESTAMP(3),

    CONSTRAINT "portfolios_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "portfolio_allocations" (
    "id" TEXT NOT NULL,
    "portfolio_id" TEXT NOT NULL,
    "allocation_type" TEXT NOT NULL,
    "target_weight" DECIMAL(9,6) NOT NULL,
    "current_weight" DECIMAL(9,6) NOT NULL DEFAULT 0,
    "allocated_amount" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "current_value" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "expected_return" DECIMAL(9,6),
    "expected_risk" DECIMAL(9,6),
    "regime" TEXT,
    "pnl" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "pnl_percentage" DECIMAL(9,6) NOT NULL DEFAULT 0,
    "realized_pnl" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "drift_percentage" DECIMAL(9,6) NOT NULL DEFAULT 0,
    "requires_rebalancing" BOOLEAN NOT NULL DEFAULT false,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "portfolio_allocations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trading_agents" (
    "id" TEXT NOT NULL,
    "portfolio_id" TEXT,
    "portfolio_allocation_id" TEXT NOT NULL,
    "agent_type" TEXT NOT NULL,
    "agent_name" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'active',
    "strategy_config" JSONB,
    "performance_metrics" JSONB,
    "realized_pnl" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "last_executed_at" TIMESTAMP(3),
    "error_count" INTEGER NOT NULL DEFAULT 0,
    "last_error_message" TEXT,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "trading_agents_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trades" (
    "id" TEXT NOT NULL,
    "organization_id" TEXT NOT NULL,
    "portfolio_id" TEXT NOT NULL,
    "agent_id" TEXT,
    "customer_id" TEXT NOT NULL,
    "trade_type" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "exchange" TEXT NOT NULL,
    "segment" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "order_type" TEXT NOT NULL,
    "quantity" INTEGER NOT NULL,
    "limit_price" DECIMAL(20,4),
    "price" DECIMAL(20,4),
    "trigger_price" DECIMAL(20,4),
    "executed_quantity" INTEGER NOT NULL DEFAULT 0,
    "executed_price" DECIMAL(20,4),
    "status" TEXT NOT NULL DEFAULT 'pending',
    "order_id" TEXT,
    "execution_time" TIMESTAMP(3),
    "rejection_reason" TEXT,
    "fees" DECIMAL(20,4),
    "taxes" DECIMAL(20,4),
    "net_amount" DECIMAL(20,4),
    "realized_pnl" DECIMAL(20,4),
    "source" TEXT,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "trades_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "positions" (
    "id" TEXT NOT NULL,
    "portfolio_id" TEXT NOT NULL,
    "agent_id" TEXT,
    "symbol" TEXT NOT NULL,
    "exchange" TEXT NOT NULL,
    "segment" TEXT NOT NULL,
    "quantity" INTEGER NOT NULL,
    "average_buy_price" DECIMAL(20,4) NOT NULL,
    "current_price" DECIMAL(20,4) NOT NULL,
    "current_value" DECIMAL(20,4) NOT NULL,
    "pnl" DECIMAL(20,4) NOT NULL DEFAULT 0,
    "pnl_percentage" DECIMAL(9,6) NOT NULL DEFAULT 0,
    "position_type" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'open',
    "opened_at" TIMESTAMP(3),
    "closed_at" TIMESTAMP(3),
    "metadata" JSONB DEFAULT '{}',
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "positions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rebalance_runs" (
    "id" TEXT NOT NULL,
    "portfolio_id" TEXT NOT NULL,
    "triggered_by" TEXT,
    "triggered_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "snapshot_portfolio_value" DECIMAL(20,4) NOT NULL,
    "snapshot_cash" DECIMAL(20,4) NOT NULL,
    "snapshot_invested" DECIMAL(20,4) NOT NULL,
    "time_elapsed_days" INTEGER,
    "expected_progress" JSONB,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "rebalance_runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "segment_snapshots" (
    "id" TEXT NOT NULL,
    "rebalance_run_id" TEXT NOT NULL,
    "segment_key" TEXT NOT NULL,
    "allocated_amount" DECIMAL(20,4) NOT NULL,
    "liquid_amount" DECIMAL(20,4) NOT NULL,
    "invested_amount" DECIMAL(20,4) NOT NULL,
    "return_pct" DECIMAL(9,6) NOT NULL,
    "volatility" DECIMAL(9,6) NOT NULL,
    "max_drawdown" DECIMAL(9,6) NOT NULL,
    "sharpe_ratio" DECIMAL(9,6),
    "metrics" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "segment_snapshots_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "allocation_snapshots" (
    "id" TEXT NOT NULL,
    "rebalance_run_id" TEXT NOT NULL,
    "portfolio_allocation_id" TEXT NOT NULL,
    "snapshot_weight" DECIMAL(9,6) NOT NULL,
    "snapshot_amount" DECIMAL(20,4) NOT NULL,
    "snapshot_current_value" DECIMAL(20,4) NOT NULL,
    "snapshot_pnl" DECIMAL(20,4) NOT NULL,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "allocation_snapshots_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trade_execution_logs" (
    "id" TEXT NOT NULL,
    "request_id" TEXT NOT NULL,
    "user_id" TEXT NOT NULL,
    "portfolio_id" TEXT,
    "symbol" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "quantity" INTEGER NOT NULL,
    "allocated_capital" DECIMAL(20,4) NOT NULL,
    "confidence" DECIMAL(9,6) NOT NULL,
    "take_profit_pct" DECIMAL(9,6) NOT NULL,
    "stop_loss_pct" DECIMAL(9,6) NOT NULL,
    "reference_price" DECIMAL(20,4) NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "signal_id" TEXT,
    "broker_order_id" TEXT,
    "executed_price" DECIMAL(20,4),
    "executed_quantity" INTEGER NOT NULL DEFAULT 0,
    "kafka_status" TEXT,
    "error_message" TEXT,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "trade_execution_logs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trading_agent_snapshots" (
    "id" TEXT NOT NULL,
    "agent_id" TEXT NOT NULL,
    "portfolio_id" TEXT NOT NULL,
    "snapshot_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "portfolio_value" DECIMAL(20,4) NOT NULL,
    "realized_pnl" DECIMAL(20,4) NOT NULL,
    "positions_count" INTEGER NOT NULL DEFAULT 0,
    "metadata" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "trading_agent_snapshots_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "objectives_user_id_idx" ON "objectives"("user_id");

-- CreateIndex
CREATE INDEX "portfolios_organization_id_idx" ON "portfolios"("organization_id");

-- CreateIndex
CREATE INDEX "portfolios_customer_id_idx" ON "portfolios"("customer_id");

-- CreateIndex
CREATE INDEX "portfolios_status_idx" ON "portfolios"("status");

-- CreateIndex
CREATE INDEX "portfolios_user_id_idx" ON "portfolios"("user_id");

-- CreateIndex
CREATE INDEX "portfolio_allocations_portfolio_id_idx" ON "portfolio_allocations"("portfolio_id");

-- CreateIndex
CREATE INDEX "portfolio_allocations_allocation_type_idx" ON "portfolio_allocations"("allocation_type");

-- CreateIndex
CREATE INDEX "trading_agents_portfolio_id_idx" ON "trading_agents"("portfolio_id");

-- CreateIndex
CREATE INDEX "trading_agents_portfolio_allocation_id_idx" ON "trading_agents"("portfolio_allocation_id");

-- CreateIndex
CREATE INDEX "trading_agents_agent_type_idx" ON "trading_agents"("agent_type");

-- CreateIndex
CREATE UNIQUE INDEX "trading_agents_portfolio_allocation_id_key" ON "trading_agents"("portfolio_allocation_id");

-- CreateIndex
CREATE INDEX "trades_organization_id_idx" ON "trades"("organization_id");

-- CreateIndex
CREATE INDEX "trades_portfolio_id_idx" ON "trades"("portfolio_id");

-- CreateIndex
CREATE INDEX "trades_customer_id_idx" ON "trades"("customer_id");

-- CreateIndex
CREATE INDEX "trades_status_idx" ON "trades"("status");

-- CreateIndex
CREATE INDEX "positions_portfolio_id_idx" ON "positions"("portfolio_id");

-- CreateIndex
CREATE INDEX "positions_agent_id_idx" ON "positions"("agent_id");

-- CreateIndex
CREATE INDEX "positions_status_idx" ON "positions"("status");

-- CreateIndex
CREATE INDEX "rebalance_runs_portfolio_id_idx" ON "rebalance_runs"("portfolio_id");

-- CreateIndex
CREATE INDEX "segment_snapshots_rebalance_run_id_idx" ON "segment_snapshots"("rebalance_run_id");

-- CreateIndex
CREATE INDEX "segment_snapshots_segment_key_idx" ON "segment_snapshots"("segment_key");

-- CreateIndex
CREATE INDEX "allocation_snapshots_rebalance_run_id_idx" ON "allocation_snapshots"("rebalance_run_id");

-- CreateIndex
CREATE INDEX "allocation_snapshots_portfolio_allocation_id_idx" ON "allocation_snapshots"("portfolio_allocation_id");

-- CreateIndex
CREATE UNIQUE INDEX "trade_execution_logs_request_id_key" ON "trade_execution_logs"("request_id");

-- CreateIndex
CREATE INDEX "trade_execution_logs_user_id_idx" ON "trade_execution_logs"("user_id");

-- CreateIndex
CREATE INDEX "trade_execution_logs_status_idx" ON "trade_execution_logs"("status");

-- CreateIndex
CREATE INDEX "trade_execution_logs_portfolio_id_idx" ON "trade_execution_logs"("portfolio_id");

-- CreateIndex
CREATE INDEX "trading_agent_snapshots_agent_id_idx" ON "trading_agent_snapshots"("agent_id");

-- CreateIndex
CREATE INDEX "trading_agent_snapshots_portfolio_id_idx" ON "trading_agent_snapshots"("portfolio_id");

-- CreateIndex
CREATE INDEX "trading_agent_snapshots_snapshot_at_idx" ON "trading_agent_snapshots"("snapshot_at");

-- AddForeignKey
ALTER TABLE "portfolios" ADD CONSTRAINT "portfolios_objective_id_fkey" FOREIGN KEY ("objective_id") REFERENCES "objectives"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "portfolio_allocations" ADD CONSTRAINT "portfolio_allocations_portfolio_id_fkey" FOREIGN KEY ("portfolio_id") REFERENCES "portfolios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trading_agents" ADD CONSTRAINT "trading_agents_portfolio_id_fkey" FOREIGN KEY ("portfolio_id") REFERENCES "portfolios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trading_agents" ADD CONSTRAINT "trading_agents_portfolio_allocation_id_fkey" FOREIGN KEY ("portfolio_allocation_id") REFERENCES "portfolio_allocations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trades" ADD CONSTRAINT "trades_portfolio_id_fkey" FOREIGN KEY ("portfolio_id") REFERENCES "portfolios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trades" ADD CONSTRAINT "trades_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "trading_agents"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "positions" ADD CONSTRAINT "positions_portfolio_id_fkey" FOREIGN KEY ("portfolio_id") REFERENCES "portfolios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "positions" ADD CONSTRAINT "positions_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "trading_agents"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "rebalance_runs" ADD CONSTRAINT "rebalance_runs_portfolio_id_fkey" FOREIGN KEY ("portfolio_id") REFERENCES "portfolios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "segment_snapshots" ADD CONSTRAINT "segment_snapshots_rebalance_run_id_fkey" FOREIGN KEY ("rebalance_run_id") REFERENCES "rebalance_runs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "allocation_snapshots" ADD CONSTRAINT "allocation_snapshots_rebalance_run_id_fkey" FOREIGN KEY ("rebalance_run_id") REFERENCES "rebalance_runs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "allocation_snapshots" ADD CONSTRAINT "allocation_snapshots_portfolio_allocation_id_fkey" FOREIGN KEY ("portfolio_allocation_id") REFERENCES "portfolio_allocations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trade_execution_logs" ADD CONSTRAINT "trade_execution_logs_portfolio_id_fkey" FOREIGN KEY ("portfolio_id") REFERENCES "portfolios"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "trading_agent_snapshots" ADD CONSTRAINT "trading_agent_snapshots_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "trading_agents"("id") ON DELETE CASCADE ON UPDATE CASCADE;
