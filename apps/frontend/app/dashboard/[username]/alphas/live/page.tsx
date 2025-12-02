"use client"

import { useEffect, useState, useCallback } from "react"
import { motion, type Variants } from "framer-motion"
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Check,
  ChevronDown,
  Database,
  Loader2,
  Play,
  RefreshCw,
  Settings,
  TrendingUp,
  Zap,
} from "lucide-react"
import { useParams } from "next/navigation"
import Link from "next/link"

import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import { apiClient } from "@/lib/api"

// Animation variants
const listVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: {
    opacity: 1,
    y: 0,
    transition: { staggerChildren: 0.06, delayChildren: 0.1 },
  },
}

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.37, 0, 0.63, 1] } },
}

// Types
interface MarketDataStatus {
  lastUpdate: string | null
  symbolsCount: number
  rowsAdded: number
  status: "idle" | "updating" | "success" | "error"
  error?: string
}

interface FactorResult {
  symbol: string
  factor_values: Record<string, number>
  timestamp: string
}

interface PredictedReturn {
  symbol: string
  predicted_return: number
  confidence: number
  rank: number
}

interface Signal {
  symbol: string
  signal_type: "buy" | "sell" | "hold"
  quantity: number
  predicted_return: number
  confidence: number
  price: number
  allocated_amount: number
  rank: number
}

interface WorkflowStatus {
  step: "idle" | "updating_data" | "computing_factors" | "running_model" | "generating_signals" | "complete" | "error"
  progress: number
  message: string
  error?: string
}

interface LiveAlphaConfig {
  id: string
  name: string
  hypothesis: string
  factors: Array<{ name: string; expression: string }>
  model_type: string
  strategy_type: string
  topk: number
  n_drop: number
  allocated_amount: number
}

// =====================================================
// MARKET DATA UPDATE COMPONENT
// =====================================================
function MarketDataCard({
  status,
  onUpdate,
}: {
  status: MarketDataStatus
  onUpdate: () => void
}) {
  return (
    <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
          <Database className="size-5 text-blue-400" />
          Market Data
        </CardTitle>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Nifty 500 daily OHLCV data from Groww API
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-xl border border-white/10 bg-white/5 p-3">
            <p className="text-xs text-white/50">Last Updated</p>
            <p className="mt-1 text-sm font-medium text-white">
              {status.lastUpdate || "Never"}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/5 p-3">
            <p className="text-xs text-white/50">Symbols</p>
            <p className="mt-1 text-sm font-medium text-white">
              {status.symbolsCount || "—"}
            </p>
          </div>
        </div>

        {status.status === "success" && status.rowsAdded > 0 && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2">
            <p className="text-xs text-emerald-200">
              ✓ Added {status.rowsAdded.toLocaleString()} new rows
            </p>
          </div>
        )}

        {status.status === "error" && status.error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2">
            <p className="text-xs text-rose-200">✗ {status.error}</p>
          </div>
        )}

        <Button
          onClick={onUpdate}
          disabled={status.status === "updating"}
          className="w-full border border-blue-500/40 bg-blue-500/20 text-blue-100 hover:bg-blue-500/30"
        >
          {status.status === "updating" ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              Updating Market Data...
            </>
          ) : (
            <>
              <RefreshCw className="mr-2 size-4" />
              Update Market Data
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

// =====================================================
// WORKFLOW STATUS COMPONENT
// =====================================================
function WorkflowStatusCard({
  status,
  onRunWorkflow,
  isRunning,
}: {
  status: WorkflowStatus
  onRunWorkflow: () => void
  isRunning: boolean
}) {
  const steps = [
    { key: "updating_data", label: "Update Data", icon: Database },
    { key: "computing_factors", label: "Compute Factors", icon: Activity },
    { key: "running_model", label: "Run ML Model", icon: BarChart3 },
    { key: "generating_signals", label: "Generate Signals", icon: TrendingUp },
  ]

  const currentStepIndex = steps.findIndex((s) => s.key === status.step)

  return (
    <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
          <Zap className="size-5 text-violet-400" />
          Live Alpha Workflow
        </CardTitle>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Generate next-day signals from latest market data
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Workflow Steps */}
        <div className="space-y-3">
          {steps.map((step, idx) => {
            const Icon = step.icon
            const isActive = step.key === status.step
            const isComplete = currentStepIndex > idx || status.step === "complete"
            const isPending = currentStepIndex < idx && status.step !== "complete"

            return (
              <div
                key={step.key}
                className={cn(
                  "flex items-center gap-3 rounded-xl border p-3 transition-all",
                  isActive && "border-violet-500/50 bg-violet-500/10",
                  isComplete && "border-emerald-500/30 bg-emerald-500/5",
                  isPending && "border-white/10 bg-white/5 opacity-50"
                )}
              >
                <div
                  className={cn(
                    "flex size-8 items-center justify-center rounded-full",
                    isActive && "bg-violet-500/30 text-violet-300",
                    isComplete && "bg-emerald-500/30 text-emerald-300",
                    isPending && "bg-white/10 text-white/40"
                  )}
                >
                  {isComplete ? (
                    <Check className="size-4" />
                  ) : isActive ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Icon className="size-4" />
                  )}
                </div>
                <div className="flex-1">
                  <p
                    className={cn(
                      "text-sm font-medium",
                      isActive && "text-violet-200",
                      isComplete && "text-emerald-200",
                      isPending && "text-white/40"
                    )}
                  >
                    {step.label}
                  </p>
                </div>
                {isActive && (
                  <span className="text-xs text-violet-300">{status.progress}%</span>
                )}
              </div>
            )
          })}
        </div>

        {/* Status Message */}
        {status.message && (
          <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
            <p className="text-xs text-white/70">{status.message}</p>
          </div>
        )}

        {/* Error */}
        {status.step === "error" && status.error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2">
            <p className="text-xs text-rose-200">✗ {status.error}</p>
          </div>
        )}

        {/* Run Button */}
        <Button
          onClick={onRunWorkflow}
          disabled={isRunning}
          className="w-full border border-violet-500/40 bg-violet-500/20 text-violet-100 hover:bg-violet-500/30"
        >
          {isRunning ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              Running Workflow...
            </>
          ) : (
            <>
              <Play className="mr-2 size-4" />
              Run Live Alpha Workflow
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

// =====================================================
// PREDICTED RETURNS TABLE
// =====================================================
function PredictedReturnsTable({
  predictions,
  loading,
}: {
  predictions: PredictedReturn[]
  loading: boolean
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-white/40" />
      </div>
    )
  }

  if (predictions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <BarChart3 className="size-12 text-white/20" />
        <p className="mt-4 text-sm text-white/60">No predictions yet</p>
        <p className="mt-1 text-xs text-white/40">
          Run the workflow to generate predicted returns
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-white/50">
            <th className="pb-3 pr-4">Rank</th>
            <th className="pb-3 pr-4">Symbol</th>
            <th className="pb-3 pr-4 text-right">Predicted Return</th>
            <th className="pb-3 text-right">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {predictions.slice(0, 50).map((pred) => {
            const isPositive = pred.predicted_return >= 0
            return (
              <motion.tr
                key={pred.symbol}
                variants={itemVariants}
                className="border-b border-white/5 text-sm"
              >
                <td className="py-3 pr-4">
                  <span className="flex size-6 items-center justify-center rounded-full bg-white/10 text-xs text-white/70">
                    {pred.rank}
                  </span>
                </td>
                <td className="py-3 pr-4 font-medium text-white">{pred.symbol}</td>
                <td className="py-3 pr-4 text-right">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 font-mono",
                      isPositive ? "text-emerald-400" : "text-rose-400"
                    )}
                  >
                    {isPositive ? (
                      <ArrowUpRight className="size-3" />
                    ) : (
                      <ArrowDownRight className="size-3" />
                    )}
                    {isPositive ? "+" : ""}
                    {(pred.predicted_return * 100).toFixed(2)}%
                  </span>
                </td>
                <td className="py-3 text-right">
                  <div className="inline-flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/10">
                      <div
                        className="h-full bg-cyan-500"
                        style={{ width: `${pred.confidence * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-white/50">
                      {(pred.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </td>
              </motion.tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// =====================================================
// SIGNALS TABLE
// =====================================================
function SignalsTable({
  signals,
  loading,
}: {
  signals: Signal[]
  loading: boolean
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-white/40" />
      </div>
    )
  }

  if (signals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <TrendingUp className="size-12 text-white/20" />
        <p className="mt-4 text-sm text-white/60">No signals generated</p>
        <p className="mt-1 text-xs text-white/40">
          Run the workflow to generate trading signals
        </p>
      </div>
    )
  }

  const buySignals = signals.filter((s) => s.signal_type === "buy")
  const sellSignals = signals.filter((s) => s.signal_type === "sell")

  return (
    <div className="space-y-6">
      {/* Buy Signals */}
      {buySignals.length > 0 && (
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-sm font-medium text-emerald-300">
            <ArrowUpRight className="size-4" />
            Buy Signals ({buySignals.length})
          </h4>
          <div className="overflow-x-auto rounded-xl border border-emerald-500/20 bg-emerald-500/5">
            <table className="w-full">
              <thead>
                <tr className="border-b border-emerald-500/20 text-left text-xs uppercase tracking-wider text-white/50">
                  <th className="p-3">Symbol</th>
                  <th className="p-3 text-right">Quantity</th>
                  <th className="p-3 text-right">Price</th>
                  <th className="p-3 text-right">Amount</th>
                  <th className="p-3 text-right">Pred. Return</th>
                </tr>
              </thead>
              <tbody>
                {buySignals.map((signal) => (
                  <tr
                    key={signal.symbol}
                    className="border-b border-emerald-500/10 text-sm"
                  >
                    <td className="p-3 font-medium text-white">{signal.symbol}</td>
                    <td className="p-3 text-right font-mono text-white/80">
                      {signal.quantity}
                    </td>
                    <td className="p-3 text-right font-mono text-white/80">
                      ₹{signal.price.toLocaleString()}
                    </td>
                    <td className="p-3 text-right font-mono text-white/80">
                      ₹{signal.allocated_amount.toLocaleString()}
                    </td>
                    <td className="p-3 text-right font-mono text-emerald-400">
                      +{(signal.predicted_return * 100).toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Sell Signals */}
      {sellSignals.length > 0 && (
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-sm font-medium text-rose-300">
            <ArrowDownRight className="size-4" />
            Sell Signals ({sellSignals.length})
          </h4>
          <div className="overflow-x-auto rounded-xl border border-rose-500/20 bg-rose-500/5">
            <table className="w-full">
              <thead>
                <tr className="border-b border-rose-500/20 text-left text-xs uppercase tracking-wider text-white/50">
                  <th className="p-3">Symbol</th>
                  <th className="p-3 text-right">Quantity</th>
                  <th className="p-3 text-right">Price</th>
                  <th className="p-3 text-right">Pred. Return</th>
                </tr>
              </thead>
              <tbody>
                {sellSignals.map((signal) => (
                  <tr key={signal.symbol} className="border-b border-rose-500/10 text-sm">
                    <td className="p-3 font-medium text-white">{signal.symbol}</td>
                    <td className="p-3 text-right font-mono text-white/80">
                      {signal.quantity}
                    </td>
                    <td className="p-3 text-right font-mono text-white/80">
                      ₹{signal.price.toLocaleString()}
                    </td>
                    <td className="p-3 text-right font-mono text-rose-400">
                      {(signal.predicted_return * 100).toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// =====================================================
// FACTOR VALUES DISPLAY
// =====================================================
function FactorValuesCard({
  factors,
  loading,
  factorConfig,
}: {
  factors: FactorResult[]
  loading: boolean
  factorConfig: Array<{ name: string; expression: string }>
}) {
  // Initialize with first factor name if available
  const firstFactorName = factorConfig.length > 0 ? factorConfig[0].name : null
  const [selectedFactor, setSelectedFactor] = useState<string | null>(firstFactorName)
  const [showDropdown, setShowDropdown] = useState(false)

  // Keep selectedFactor in sync with factorConfig changes (when it becomes available)
  const currentSelectedFactor = selectedFactor ?? firstFactorName

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-white/40" />
      </div>
    )
  }

  if (factors.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Activity className="size-12 text-white/20" />
        <p className="mt-4 text-sm text-white/60">No factor values computed</p>
        <p className="mt-1 text-xs text-white/40">
          Run the workflow to compute factor values
        </p>
      </div>
    )
  }

  // Get top/bottom stocks by selected factor
  const sortedByFactor = [...factors]
    .filter((f) => currentSelectedFactor && f.factor_values[currentSelectedFactor] !== undefined)
    .sort((a, b) => {
      if (!currentSelectedFactor) return 0
      return (b.factor_values[currentSelectedFactor] || 0) - (a.factor_values[currentSelectedFactor] || 0)
    })

  const topStocks = sortedByFactor.slice(0, 10)
  const bottomStocks = sortedByFactor.slice(-10).reverse()

  return (
    <div className="space-y-4">
      {/* Factor Selector */}
      <div className="relative">
        <button
          onClick={() => setShowDropdown(!showDropdown)}
          className="flex w-full items-center justify-between rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white"
        >
          <span>{currentSelectedFactor || "Select Factor"}</span>
          <ChevronDown
            className={cn("size-4 transition-transform", showDropdown && "rotate-180")}
          />
        </button>
        {showDropdown && (
          <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-60 overflow-y-auto rounded-xl border border-white/15 bg-black/95 py-2 shadow-xl">
            {factorConfig.map((factor) => (
              <button
                key={factor.name}
                onClick={() => {
                  setSelectedFactor(factor.name)
                  setShowDropdown(false)
                }}
                className={cn(
                  "w-full px-4 py-2 text-left text-sm hover:bg-white/10",
                  currentSelectedFactor === factor.name
                    ? "bg-violet-500/20 text-violet-200"
                    : "text-white/80"
                )}
              >
                <div className="font-medium">{factor.name}</div>
                <div className="mt-0.5 truncate text-xs text-white/50">
                  {factor.expression}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Top/Bottom Display */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Top 10 */}
        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
          <h4 className="mb-3 text-sm font-medium text-emerald-300">
            Top 10 by {currentSelectedFactor}
          </h4>
          <div className="space-y-2">
            {topStocks.map((stock, idx) => (
              <div
                key={stock.symbol}
                className="flex items-center justify-between text-sm"
              >
                <span className="flex items-center gap-2">
                  <span className="flex size-5 items-center justify-center rounded-full bg-emerald-500/20 text-xs text-emerald-300">
                    {idx + 1}
                  </span>
                  <span className="font-medium text-white">{stock.symbol}</span>
                </span>
                <span className="font-mono text-emerald-400">
                  {currentSelectedFactor &&
                    stock.factor_values[currentSelectedFactor]?.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom 10 */}
        <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4">
          <h4 className="mb-3 text-sm font-medium text-rose-300">
            Bottom 10 by {currentSelectedFactor}
          </h4>
          <div className="space-y-2">
            {bottomStocks.map((stock, idx) => (
              <div
                key={stock.symbol}
                className="flex items-center justify-between text-sm"
              >
                <span className="flex items-center gap-2">
                  <span className="flex size-5 items-center justify-center rounded-full bg-rose-500/20 text-xs text-rose-300">
                    {sortedByFactor.length - 9 + idx}
                  </span>
                  <span className="font-medium text-white">{stock.symbol}</span>
                </span>
                <span className="font-mono text-rose-400">
                  {currentSelectedFactor &&
                    stock.factor_values[currentSelectedFactor]?.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// =====================================================
// ALPHA CONFIG SELECTOR
// =====================================================
function AlphaConfigSelector({
  configs,
  selectedId,
  onSelect,
}: {
  configs: LiveAlphaConfig[]
  selectedId: string | null
  onSelect: (config: LiveAlphaConfig) => void
}) {
  const [showDropdown, setShowDropdown] = useState(false)
  const selected = configs.find((c) => c.id === selectedId)

  return (
    <div className="relative">
      <button
        onClick={() => setShowDropdown(!showDropdown)}
        className="flex w-full items-center justify-between rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-left"
      >
        <div className="min-w-0 flex-1">
          {selected ? (
            <>
              <p className="text-sm font-medium text-white">{selected.name}</p>
              <p className="mt-0.5 truncate text-xs text-white/50">
                {selected.model_type} • {selected.strategy_type} • Top-{selected.topk}
              </p>
            </>
          ) : (
            <p className="text-sm text-white/50">Select a Live Alpha</p>
          )}
        </div>
        <ChevronDown
          className={cn("ml-2 size-4 text-white/50 transition-transform", showDropdown && "rotate-180")}
        />
      </button>

      {showDropdown && (
        <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-80 overflow-y-auto rounded-xl border border-white/15 bg-black/95 py-2 shadow-xl">
          {configs.length === 0 ? (
            <div className="px-4 py-3 text-center text-sm text-white/50">
              No live alphas deployed
            </div>
          ) : (
            configs.map((config) => (
              <button
                key={config.id}
                onClick={() => {
                  onSelect(config)
                  setShowDropdown(false)
                }}
                className={cn(
                  "w-full px-4 py-3 text-left hover:bg-white/10",
                  selectedId === config.id && "bg-violet-500/20"
                )}
              >
                <p className="text-sm font-medium text-white">{config.name}</p>
                <p className="mt-0.5 line-clamp-1 text-xs text-white/50">
                  {config.hypothesis}
                </p>
                <div className="mt-1 flex items-center gap-2 text-xs text-white/40">
                  <span>{config.model_type}</span>
                  <span>•</span>
                  <span>{config.strategy_type}</span>
                  <span>•</span>
                  <span>Top-{config.topk}</span>
                  <span>•</span>
                  <span>₹{config.allocated_amount.toLocaleString()}</span>
                </div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// =====================================================
// MAIN PAGE COMPONENT
// =====================================================
export default function LiveAlphaPage() {
  const params = useParams()
  const username = params.username as string

  // Auth
  const { user: authUser, loading: authLoading } = useAuth()

  // State
  const [alphaConfigs, setAlphaConfigs] = useState<LiveAlphaConfig[]>([])
  const [selectedAlpha, setSelectedAlpha] = useState<LiveAlphaConfig | null>(null)
  const [marketDataStatus, setMarketDataStatus] = useState<MarketDataStatus>({
    lastUpdate: null,
    symbolsCount: 0,
    rowsAdded: 0,
    status: "idle",
  })
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>({
    step: "idle",
    progress: 0,
    message: "",
  })
  const [factorResults, setFactorResults] = useState<FactorResult[]>([])
  const [predictions, setPredictions] = useState<PredictedReturn[]>([])
  const [signals, setSignals] = useState<Signal[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const [configsLoading, setConfigsLoading] = useState(true)

  // Fetch live alpha configs
  useEffect(() => {
    const fetchConfigs = async () => {
      try {
        const data = await apiClient.get<{ alphas: Record<string, unknown>[] }>("/api/alphas/live")
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const configs = data.alphas.map((alpha: Record<string, any>) => ({
          id: alpha.id,
          name: alpha.name,
          hypothesis: alpha.hypothesis || "",
          factors: alpha.workflow_config?.features || [],
          model_type: alpha.model_type || "LightGBM",
          strategy_type: alpha.strategy_type || "TopkDropout",
          topk: alpha.workflow_config?.strategy?.params?.topk || 30,
          n_drop: alpha.workflow_config?.strategy?.params?.n_drop || 5,
          allocated_amount: alpha.allocated_amount || 100000,
        }))
        setAlphaConfigs(configs)
        // Set initial selection only if nothing is selected yet
        setSelectedAlpha((prev) => prev ?? configs[0] ?? null)
      } catch (error) {
        console.error("Failed to fetch alpha configs:", error)
      } finally {
        setConfigsLoading(false)
      }
    }

    fetchConfigs()
  }, [])

  // Check market data status on mount
  useEffect(() => {
    const checkMarketDataStatus = async () => {
      try {
        const status = await apiClient.get<{
          last_date: string | null
          rows_count: number
          symbols_count: number
          is_up_to_date: boolean
          message: string
        }>("/api/alphas/market-data-status")
        
        setMarketDataStatus({
          lastUpdate: status.last_date,
          symbolsCount: status.symbols_count,
          rowsAdded: 0,
          status: status.is_up_to_date ? "success" : "idle",
        })
      } catch (error) {
        console.error("Failed to check market data status:", error)
      }
    }
    
    checkMarketDataStatus()
  }, [])

  // Update market data
  const handleUpdateMarketData = useCallback(async () => {
    setMarketDataStatus((prev) => ({ ...prev, status: "updating", error: undefined }))

    try {
      const result = await apiClient.post<{ symbols_count?: number; rows_added?: number; message?: string }>("/api/alphas/update-market-data")

      setMarketDataStatus({
        lastUpdate: new Date().toLocaleString(),
        symbolsCount: result.symbols_count || 500,
        rowsAdded: result.rows_added || 0,
        status: "success",
      })
    } catch (error) {
      setMarketDataStatus((prev) => ({
        ...prev,
        status: "error",
        error: error instanceof Error ? error.message : "Unknown error",
      }))
    }
  }, [])

  // Run full workflow
  const handleRunWorkflow = useCallback(async () => {
    if (!selectedAlpha) {
      setWorkflowStatus({
        step: "error",
        progress: 0,
        message: "",
        error: "Please select a Live Alpha first",
      })
      return
    }

    setIsRunning(true)
    setFactorResults([])
    setPredictions([])
    setSignals([])

    try {
      // Step 1: Check market data status first, only update if needed
      setWorkflowStatus({
        step: "updating_data",
        progress: 5,
        message: "Checking market data status...",
      })

      const status = await apiClient.get<{
        last_date: string | null
        is_up_to_date: boolean
        symbols_count: number
      }>("/api/alphas/market-data-status")

      if (!status.is_up_to_date) {
        setWorkflowStatus({
          step: "updating_data",
          progress: 10,
          message: "Fetching latest market data from Groww API (this may take a few minutes)...",
        })
        await apiClient.post("/api/alphas/update-market-data")
      } else {
        setWorkflowStatus({
          step: "updating_data",
          progress: 20,
          message: `Market data is up to date (last: ${status.last_date})`,
        })
      }

      // Step 2: Compute factors
      setWorkflowStatus({
        step: "computing_factors",
        progress: 30,
        message: `Computing ${selectedAlpha.factors.length} factor expressions...`,
      })

      try {
        const factorsData = await apiClient.post<{ factors?: FactorResult[] }>(
          `/api/alphas/live/${selectedAlpha.id}/compute-factors`
        )
        setFactorResults(factorsData.factors || [])
      } catch {
        // Continue even if factors fail
      }

      // Step 3: Run ML model for return predictions
      setWorkflowStatus({
        step: "running_model",
        progress: 60,
        message: `Running ${selectedAlpha.model_type} model for return predictions...`,
      })

      try {
        const predictionsData = await apiClient.post<{ predictions?: PredictedReturn[] }>(
          `/api/alphas/live/${selectedAlpha.id}/predict-returns`
        )
        setPredictions(predictionsData.predictions || [])
      } catch {
        // Continue even if predictions fail
      }

      // Step 4: Generate signals using strategy
      setWorkflowStatus({
        step: "generating_signals",
        progress: 85,
        message: `Applying ${selectedAlpha.strategy_type} strategy (top-${selectedAlpha.topk})...`,
      })

      let signalCount = 0
      try {
        const signalsData = await apiClient.post<{ signals?: Signal[] }>(
          `/api/alphas/live/${selectedAlpha.id}/generate-signals`
        )
        const newSignals = signalsData.signals || []
        setSignals(newSignals)
        signalCount = newSignals.length
      } catch {
        // Continue even if signals fail
      }

      // Complete
      setWorkflowStatus({
        step: "complete",
        progress: 100,
        message: `Generated ${signalCount} trading signals for next trading day`,
      })
    } catch (error) {
      setWorkflowStatus({
        step: "error",
        progress: 0,
        message: "",
        error: error instanceof Error ? error.message : "Workflow failed",
      })
    } finally {
      setIsRunning(false)
    }
  }, [selectedAlpha])

  // Loading state
  if (authLoading || !authUser) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0c0c0c] text-[#fafafa]">
        <Loader2 className="size-6 animate-spin text-white/60" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader
        userName={authUser.firstName}
        username={username}
        userRole={authUser.role}
      />

      <main>
        <Container className="no-scrollbar max-w-10xl space-y-6 py-8">
          <PageHeading
            tagline="Run models on latest data, generate next-day trading signals"
            title="Live Alpha Signals"
            action={
              <Link href={`/dashboard/${username}/alphas`}>
                <Button
                  variant="outline"
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  ← Back to Alphas
                </Button>
              </Link>
            }
          />

          {/* Alpha Selector */}
          <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                <Settings className="size-5 text-cyan-400" />
                Select Live Alpha
              </CardTitle>
              <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                Choose which deployed alpha to run on latest market data
              </CardDescription>
            </CardHeader>
            <CardContent>
              {configsLoading ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="size-5 animate-spin text-white/40" />
                </div>
              ) : (
                <AlphaConfigSelector
                  configs={alphaConfigs}
                  selectedId={selectedAlpha?.id || null}
                  onSelect={setSelectedAlpha}
                />
              )}

              {selectedAlpha && (
                <div className="mt-4 rounded-xl border border-white/10 bg-white/5 p-4">
                  <div className="grid gap-3 text-sm md:grid-cols-2 lg:grid-cols-4">
                    <div>
                      <p className="text-xs text-white/50">Model Type</p>
                      <p className="mt-1 font-medium text-white">{selectedAlpha.model_type}</p>
                    </div>
                    <div>
                      <p className="text-xs text-white/50">Strategy</p>
                      <p className="mt-1 font-medium text-white">{selectedAlpha.strategy_type}</p>
                    </div>
                    <div>
                      <p className="text-xs text-white/50">Top-K / N-Drop</p>
                      <p className="mt-1 font-medium text-white">
                        {selectedAlpha.topk} / {selectedAlpha.n_drop}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-white/50">Allocated Capital</p>
                      <p className="mt-1 font-medium text-white">
                        ₹{selectedAlpha.allocated_amount.toLocaleString()}
                      </p>
                    </div>
                  </div>
                  {selectedAlpha.factors.length > 0 && (
                    <div className="mt-3 border-t border-white/10 pt-3">
                      <p className="text-xs text-white/50">
                        Factors: {selectedAlpha.factors.length}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {selectedAlpha.factors.slice(0, 5).map((f) => (
                          <span
                            key={f.name}
                            className="rounded-full bg-violet-500/20 px-2 py-0.5 text-xs text-violet-300"
                          >
                            {f.name}
                          </span>
                        ))}
                        {selectedAlpha.factors.length > 5 && (
                          <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/50">
                            +{selectedAlpha.factors.length - 5} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  <div className="mt-4 flex justify-end">
                    <Link href={`/dashboard/${username}/alphas/live/${selectedAlpha.id}`}>
                      <Button
                        variant="outline"
                        className="border-cyan-500/40 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20"
                      >
                        View Signal History & Execute Trades →
                      </Button>
                    </Link>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Workflow Controls */}
          <div className="grid gap-6 lg:grid-cols-2">
            <MarketDataCard status={marketDataStatus} onUpdate={handleUpdateMarketData} />
            <WorkflowStatusCard
              status={workflowStatus}
              onRunWorkflow={handleRunWorkflow}
              isRunning={isRunning}
            />
          </div>

          {/* Results Section */}
          {(factorResults.length > 0 || predictions.length > 0 || signals.length > 0) && (
            <div className="space-y-6">
              {/* Signals */}
              <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                    <TrendingUp className="size-5 text-emerald-400" />
                    Trading Signals for Next Day
                  </CardTitle>
                  <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                    Based on {selectedAlpha?.strategy_type} strategy with top-
                    {selectedAlpha?.topk} stocks
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <SignalsTable signals={signals} loading={isRunning} />
                </CardContent>
              </Card>

              {/* Predicted Returns */}
              <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                    <BarChart3 className="size-5 text-cyan-400" />
                    Predicted Returns
                  </CardTitle>
                  <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                    {selectedAlpha?.model_type} model predictions ranked by expected return
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <motion.div variants={listVariants} initial="hidden" animate="show">
                    <PredictedReturnsTable predictions={predictions} loading={isRunning} />
                  </motion.div>
                </CardContent>
              </Card>

              {/* Factor Values */}
              <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                    <Activity className="size-5 text-violet-400" />
                    Factor Values
                  </CardTitle>
                  <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                    Computed factor values for all symbols
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <FactorValuesCard
                    factors={factorResults}
                    loading={isRunning}
                    factorConfig={selectedAlpha?.factors || []}
                  />
                </CardContent>
              </Card>
            </div>
          )}
        </Container>
      </main>
    </div>
  )
}
