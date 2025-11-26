"use client"

import { motion, type Variants } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { AgentDashboard } from "@/lib/types/agent"
import { formatCurrency, formatPercentage, formatWeight, displayValue } from "@/lib/utils/formatters"
import { AllocationLoadingState } from "@/components/shared/AllocationLoadingState"

const container: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: {
    opacity: 1,
    y: 0,
    transition: { staggerChildren: 0.08, duration: 0.4, ease: [0.37, 0, 0.63, 1] },
  },
}

const item: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0 },
}

interface AgentOverviewProps {
  data: AgentDashboard | null
  loading: boolean
  isAllocating?: boolean
}

export function AgentOverview({ data, loading, isAllocating = false }: AgentOverviewProps) {
  // Show allocating message when agents are being created
  if (isAllocating) {
    return (
      <AllocationLoadingState
        title="Allocating Your Portfolio"
        description="We're setting up your trading agents and allocating your portfolio. This usually takes a few moments."
        steps={[
          "Creating agent instances...",
          "Calculating optimal allocations...",
          "Initializing trading strategies...",
        ]}
        asCard
      />
    )
  }

  if (loading || !data) {
    return (
      <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
        <CardHeader>
          <CardTitle className="h-title text-xl text-[#fafafa]">Agent Overview</CardTitle>
          <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
            Loading agent data...
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div
                key={i}
                className="animate-pulse rounded-xl border border-white/10 bg-white/8 p-4"
              >
                <div className="h-3 w-20 rounded bg-white/20" />
                <div className="mt-2 h-7 w-32 rounded bg-white/20" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  const statusColor = {
    active: "bg-emerald-500/15 text-emerald-200",
    paused: "bg-amber-500/15 text-amber-200",
    stopped: "bg-rose-500/15 text-rose-200",
    error: "bg-red-500/15 text-red-200",
  }[data.status] || "bg-gray-500/15 text-gray-200"

  const pnlValue = parseFloat(data.realized_pnl || "0")
  const isPnlPositive = pnlValue >= 0

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="h-title text-xl text-[#fafafa]">{data.agent_name}</CardTitle>
          <span
            className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase ${statusColor}`}
          >
            {data.status}
          </span>
        </div>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Agent Performance
        </CardDescription>
      </CardHeader>
      <CardContent>
        <motion.div
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
          variants={container}
          initial="hidden"
          animate="show"
        >
          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Current Value</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatCurrency(data.current_value)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Realized PnL</p>
            <p className={`mt-2 text-2xl font-semibold ${isPnlPositive ? "text-emerald-300" : "text-rose-300"}`}>
              {formatCurrency(data.realized_pnl)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Positions</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">{data.positions_count}</p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Target Weight</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatWeight(data.allocation.target_weight)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Current Weight</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatWeight(data.allocation.current_weight)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Allocated Amount</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatCurrency(data.allocation.allocated_amount)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Available Cash</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatCurrency(data.allocation.available_cash)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Expected Return</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatPercentage(data.allocation.expected_return)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Expected Risk</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatPercentage(data.allocation.expected_risk)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Regime</p>
            <p className="mt-2 text-lg font-semibold text-[#fafafa]">
              {displayValue(data.allocation.regime).replace(/_/g, " ").toUpperCase()}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">PnL</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatCurrency(data.allocation.pnl)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">PnL %</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatPercentage(data.allocation.pnl_percentage)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Drift %</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatPercentage(data.allocation.drift_percentage)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Rebalancing</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {data.allocation.requires_rebalancing ? (
                <span className="text-amber-300">Required</span>
              ) : (
                <span className="text-emerald-300">Not Required</span>
              )}
            </p>
          </motion.div>
        </motion.div>
      </CardContent>
    </Card>
  )
}

