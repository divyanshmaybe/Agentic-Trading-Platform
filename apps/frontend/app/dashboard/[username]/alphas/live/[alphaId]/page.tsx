"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { motion, type Variants } from "framer-motion"
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  ArrowLeft,
  BarChart3,
  Check,
  ChevronRight,
  Database,
  Loader2,
  Play,
  RefreshCw,
  TrendingUp,
  Zap,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
} from "lucide-react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"

import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import { apiClient } from "@/lib/api"
import { type TaskStatusResponse } from "@/hooks/useAlphas"

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
interface LiveAlpha {
  id: string
  name: string
  hypothesis: string | null
  run_id: string | null
  workflow_config: {
    features?: Array<{ name: string; expression: string }>
    model?: { type: string }
    strategy?: { type: string; params?: { topk?: number; n_drop?: number } }
    experiment?: { run_id?: string; mlflow_run_id?: string }
  }
  symbols: string[]
  model_type: string | null
  strategy_type: string
  status: string
  allocated_amount: number
  portfolio_id: string
  agent_id: string | null
  last_signal_at: string | null
  total_signals: number
  created_at: string
  updated_at: string
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

interface AlphaSignal {
  id: string
  live_alpha_id: string
  batch_id: string
  symbol: string
  signal_type: string
  quantity: number
  predicted_return: number
  confidence: number
  price: number
  allocated_amount: number
  rank: number | null
  status: string
  generated_at: string
  executed_at: string | null
  expires_at: string | null
  trade_id: string | null
}

interface SignalBatch {
  batch_id: string
  generated_at: string
  signals_count: number
  pending_count: number
  executed_count: number
  expired_count: number
  signals: AlphaSignal[]
}

interface WorkflowStatus {
  step: "idle" | "queued" | "running" | "loading_data" | "computing_factors" | "running_model" | "generating_signals" | "complete" | "error"
  progress: number
  message: string
  error?: string
  taskId?: string
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
  const isProcessing = ["queued", "running", "loading_data", "computing_factors", "running_model", "generating_signals"].includes(status.step)
  
  const getStatusIcon = () => {
    switch (status.step) {
      case "idle":
        return <Play className="size-5" />
      case "queued":
        return <Clock className="size-5 animate-pulse" />
      case "loading_data":
        return <Database className="size-5 animate-pulse" />
      case "computing_factors":
        return <BarChart3 className="size-5 animate-pulse" />
      case "running_model":
        return <TrendingUp className="size-5 animate-pulse" />
      case "generating_signals":
        return <Zap className="size-5 animate-pulse" />
      case "running":
        return <Loader2 className="size-5 animate-spin" />
      case "complete":
        return <CheckCircle2 className="size-5" />
      case "error":
        return <XCircle className="size-5" />
      default:
        return <Play className="size-5" />
    }
  }

  const getStatusColor = () => {
    switch (status.step) {
      case "idle":
        return "text-white/60"
      case "queued":
        return "text-amber-400"
      case "loading_data":
        return "text-blue-400"
      case "computing_factors":
        return "text-cyan-400"
      case "running_model":
        return "text-violet-400"
      case "generating_signals":
        return "text-fuchsia-400"
      case "running":
        return "text-violet-400"
      case "complete":
        return "text-emerald-400"
      case "error":
        return "text-rose-400"
      default:
        return "text-white/60"
    }
  }

  const getStatusLabel = () => {
    switch (status.step) {
      case "idle":
        return "Ready to generate"
      case "queued":
        return "Queued for processing..."
      case "loading_data":
        return "Loading market data..."
      case "computing_factors":
        return "Computing factors..."
      case "running_model":
        return "Running ML model..."
      case "generating_signals":
        return "Generating signals..."
      case "running":
        return "Processing..."
      case "complete":
        return "Complete"
      case "error":
        return "Failed"
      default:
        return "Ready"
    }
  }
  
  const getBorderClass = () => {
    if (status.step === "idle") return "border-white/10 bg-white/5"
    if (status.step === "queued") return "border-amber-500/30 bg-amber-500/10"
    if (status.step === "complete") return "border-emerald-500/30 bg-emerald-500/10"
    if (status.step === "error") return "border-rose-500/30 bg-rose-500/10"
    // All processing states
    return "border-violet-500/30 bg-violet-500/10"
  }

  return (
    <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
          <Zap className="size-5 text-violet-400" />
          Signal Generation
        </CardTitle>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Generate trading signals via background task
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Status Display */}
        <div
          className={cn(
            "flex items-center gap-4 rounded-xl border p-4 transition-all",
            getBorderClass()
          )}
        >
          <div className={cn("flex size-12 items-center justify-center rounded-full bg-white/10", getStatusColor())}>
            {getStatusIcon()}
          </div>
          <div className="flex-1">
            <p className={cn("text-sm font-semibold", getStatusColor())}>
              {getStatusLabel()}
            </p>
            {status.message && (
              <p className="mt-1 text-xs text-white/50">{status.message}</p>
            )}
            {status.error && (
              <p className="mt-1 text-xs text-rose-300">{status.error}</p>
            )}
            {status.taskId && (
              <p className="mt-1 font-mono text-xs text-white/30">
                Task: {status.taskId.slice(0, 8)}...
              </p>
            )}
          </div>
          {isProcessing && (
            <div className="text-right">
              <p className="text-2xl font-bold text-violet-300">{status.progress}%</p>
            </div>
          )}
        </div>

        {/* Progress Bar */}
        {isProcessing && (
          <div className="h-2 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full bg-gradient-to-r from-violet-500 to-violet-400 transition-all duration-500"
              style={{ width: `${status.progress}%` }}
            />
          </div>
        )}

        {/* Status Message - only show if not already shown in the status display */}
        {status.message && isProcessing && (
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
              Generate New Signals
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

// =====================================================
// SIGNAL HISTORY TABLE
// =====================================================
function SignalHistoryTable({
  batches,
  loading,
  onExecuteSignal,
  onExecuteAll,
  executingSignals,
}: {
  batches: SignalBatch[]
  loading: boolean
  onExecuteSignal: (signalId: string) => void
  onExecuteAll: (batchId: string) => void
  executingSignals: Set<string>
}) {
  const [expandedBatches, setExpandedBatches] = useState<Set<string>>(new Set())

  const toggleBatch = (batchId: string) => {
    setExpandedBatches((prev) => {
      const next = new Set(prev)
      if (next.has(batchId)) {
        next.delete(batchId)
      } else {
        next.add(batchId)
      }
      return next
    })
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "pending":
        return <Clock className="size-4 text-amber-400" />
      case "executed":
        return <CheckCircle2 className="size-4 text-emerald-400" />
      case "expired":
        return <XCircle className="size-4 text-gray-400" />
      case "cancelled":
        return <AlertCircle className="size-4 text-rose-400" />
      case "skipped":
        return <AlertCircle className="size-4 text-orange-400" />
      default:
        return <Clock className="size-4 text-white/40" />
    }
  }

  const getStatusBadge = (status: string) => {
    const styles = {
      pending: "bg-amber-500/20 text-amber-300 border-amber-500/30",
      executed: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
      expired: "bg-gray-500/20 text-gray-400 border-gray-500/30",
      cancelled: "bg-rose-500/20 text-rose-300 border-rose-500/30",
      skipped: "bg-orange-500/20 text-orange-300 border-orange-500/30",
    }
    return styles[status as keyof typeof styles] || styles.pending
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-white/40" />
      </div>
    )
  }

  if (batches.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <TrendingUp className="size-12 text-white/20" />
        <p className="mt-4 text-sm text-white/60">No signal history</p>
        <p className="mt-1 text-xs text-white/40">
          Run the workflow to generate trading signals
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {batches.map((batch) => {
        const isExpanded = expandedBatches.has(batch.batch_id)
        const generatedDate = new Date(batch.generated_at)

        return (
          <div
            key={batch.batch_id}
            className="overflow-hidden rounded-xl border border-white/10 bg-white/5"
          >
            {/* Batch Header */}
            <button
              onClick={() => toggleBatch(batch.batch_id)}
              className="flex w-full items-center justify-between p-4 text-left hover:bg-white/5"
            >
              <div className="flex items-center gap-3">
                <ChevronRight
                  className={cn(
                    "size-4 text-white/50 transition-transform",
                    isExpanded && "rotate-90"
                  )}
                />
                <div>
                  <p className="text-sm font-medium text-white">
                    {generatedDate.toLocaleDateString("en-IN", {
                      weekday: "short",
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })}
                  </p>
                  <p className="text-xs text-white/50">
                    {generatedDate.toLocaleTimeString("en-IN", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 text-xs">
                  <span className="rounded-full bg-white/10 px-2 py-0.5">
                    {batch.signals_count} signals
                  </span>
                  {batch.pending_count > 0 && (
                    <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-amber-300">
                      {batch.pending_count} pending
                    </span>
                  )}
                  {batch.executed_count > 0 && (
                    <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-emerald-300">
                      {batch.executed_count} executed
                    </span>
                  )}
                </div>
              </div>
            </button>

            {/* Expanded Content */}
            {isExpanded && (
              <div className="border-t border-white/10 p-4">
                {/* Execute All Button */}
                {batch.pending_count > 0 && (
                  <div className="mb-4">
                    <Button
                      onClick={() => onExecuteAll(batch.batch_id)}
                      disabled={executingSignals.has(`batch-${batch.batch_id}`)}
                      className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
                    >
                      {executingSignals.has(`batch-${batch.batch_id}`) ? (
                        <>
                          <Loader2 className="mr-2 size-4 animate-spin" />
                          Executing All...
                        </>
                      ) : (
                        <>
                          <Play className="mr-2 size-4" />
                          Execute All {batch.pending_count} Pending Signals
                        </>
                      )}
                    </Button>
                  </div>
                )}

                {/* Signals Table */}
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-white/50">
                        <th className="pb-3 pr-4">Status</th>
                        <th className="pb-3 pr-4">Symbol</th>
                        <th className="pb-3 pr-4">Type</th>
                        <th className="pb-3 pr-4 text-right">Qty</th>
                        <th className="pb-3 pr-4 text-right">Price</th>
                        <th className="pb-3 pr-4 text-right">Amount</th>
                        <th className="pb-3 pr-4 text-right">Pred. Return</th>
                        <th className="pb-3">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batch.signals.map((signal) => (
                        <tr
                          key={signal.id}
                          className="border-b border-white/5 text-sm"
                        >
                          <td className="py-3 pr-4">
                            <div className="flex items-center gap-2">
                              {getStatusIcon(signal.status)}
                              <span
                                className={cn(
                                  "rounded-full border px-2 py-0.5 text-xs",
                                  getStatusBadge(signal.status)
                                )}
                              >
                                {signal.status}
                              </span>
                            </div>
                          </td>
                          <td className="py-3 pr-4 font-medium text-white">
                            {signal.symbol}
                          </td>
                          <td className="py-3 pr-4">
                            <span
                              className={cn(
                                "inline-flex items-center gap-1 text-xs font-medium",
                                signal.signal_type === "buy"
                                  ? "text-emerald-400"
                                  : "text-rose-400"
                              )}
                            >
                              {signal.signal_type === "buy" ? (
                                <ArrowUpRight className="size-3" />
                              ) : (
                                <ArrowDownRight className="size-3" />
                              )}
                              {signal.signal_type.toUpperCase()}
                            </span>
                          </td>
                          <td className="py-3 pr-4 text-right font-mono text-white/80">
                            {signal.quantity}
                          </td>
                          <td className="py-3 pr-4 text-right font-mono text-white/80">
                            ₹{signal.price.toLocaleString()}
                          </td>
                          <td className="py-3 pr-4 text-right font-mono text-white/80">
                            ₹{signal.allocated_amount.toLocaleString()}
                          </td>
                          <td className="py-3 pr-4 text-right">
                            <span
                              className={cn(
                                "font-mono",
                                signal.predicted_return >= 0
                                  ? "text-emerald-400"
                                  : "text-rose-400"
                              )}
                            >
                              {signal.predicted_return >= 0 ? "+" : ""}
                              {(signal.predicted_return * 100).toFixed(2)}%
                            </span>
                          </td>
                          <td className="py-3">
                            {signal.status === "pending" ? (
                              <Button
                                size="sm"
                                onClick={() => onExecuteSignal(signal.id)}
                                disabled={executingSignals.has(signal.id)}
                                className="h-7 border border-emerald-500/40 bg-emerald-500/20 px-2 text-xs text-emerald-100 hover:bg-emerald-500/30"
                              >
                                {executingSignals.has(signal.id) ? (
                                  <Loader2 className="size-3 animate-spin" />
                                ) : (
                                  "Execute"
                                )}
                              </Button>
                            ) : signal.trade_id ? (
                              <span className="text-xs text-white/40">
                                Trade: {signal.trade_id.slice(0, 8)}...
                              </span>
                            ) : (
                              <span className="text-xs text-white/40">—</span>
                            )}
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
      })}
    </div>
  )
}

// =====================================================
// CURRENT SIGNALS TABLE (from latest workflow run)
// =====================================================
function CurrentSignalsTable({
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
        <p className="mt-4 text-sm text-white/60">No signals generated yet</p>
        <p className="mt-1 text-xs text-white/40">
          Run the workflow above to generate trading signals
        </p>
      </div>
    )
  }

  const buySignals = signals.filter((s) => s.signal_type === "buy")

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-white/50">
            <th className="pb-3 pr-4">Rank</th>
            <th className="pb-3 pr-4">Symbol</th>
            <th className="pb-3 pr-4 text-right">Quantity</th>
            <th className="pb-3 pr-4 text-right">Price</th>
            <th className="pb-3 pr-4 text-right">Amount</th>
            <th className="pb-3 text-right">Pred. Return</th>
          </tr>
        </thead>
        <tbody>
          {buySignals.map((signal) => (
            <motion.tr
              key={signal.symbol}
              variants={itemVariants}
              className="border-b border-white/5 text-sm"
            >
              <td className="py-3 pr-4">
                <span className="flex size-6 items-center justify-center rounded-full bg-emerald-500/20 text-xs text-emerald-300">
                  {signal.rank}
                </span>
              </td>
              <td className="py-3 pr-4 font-medium text-white">{signal.symbol}</td>
              <td className="py-3 pr-4 text-right font-mono text-white/80">
                {signal.quantity}
              </td>
              <td className="py-3 pr-4 text-right font-mono text-white/80">
                ₹{signal.price.toLocaleString()}
              </td>
              <td className="py-3 pr-4 text-right font-mono text-white/80">
                ₹{signal.allocated_amount.toLocaleString()}
              </td>
              <td className="py-3 text-right font-mono text-emerald-400">
                +{(signal.predicted_return * 100).toFixed(2)}%
              </td>
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// =====================================================
// MAIN PAGE COMPONENT
// =====================================================
export default function LiveAlphaDetailPage() {
  const params = useParams()
  const router = useRouter()
  const username = params.username as string
  const alphaId = params.alphaId as string

  // Auth
  const { user: authUser, loading: authLoading } = useAuth()

  // State
  const [alpha, setAlpha] = useState<LiveAlpha | null>(null)
  const [alphaLoading, setAlphaLoading] = useState(true)
  const [signalBatches, setSignalBatches] = useState<SignalBatch[]>([])
  const [signalsLoading, setSignalsLoading] = useState(true)
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>({
    step: "idle",
    progress: 0,
    message: "",
  })
  const [currentSignals, setCurrentSignals] = useState<Signal[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const [executingSignals, setExecutingSignals] = useState<Set<string>>(new Set())

  // Fetch alpha details
  useEffect(() => {
    const fetchAlpha = async () => {
      try {
        const data = await apiClient.get<LiveAlpha>(`/api/alphas/live/${alphaId}`)
        setAlpha(data)
      } catch (error) {
        console.error("Failed to fetch alpha:", error)
        router.push(`/dashboard/${username}/alphas/live`)
      } finally {
        setAlphaLoading(false)
      }
    }

    fetchAlpha()
  }, [alphaId, username, router])

  // Fetch signal history
  const fetchSignalHistory = useCallback(async () => {
    try {
      setSignalsLoading(true)
      const data = await apiClient.get<{ batches: SignalBatch[] }>(
        `/api/alphas/live/${alphaId}/signals`
      )
      setSignalBatches(data.batches || [])
    } catch (error) {
      console.error("Failed to fetch signals:", error)
    } finally {
      setSignalsLoading(false)
    }
  }, [alphaId])

  useEffect(() => {
    fetchSignalHistory()
  }, [fetchSignalHistory])

  // Polling interval ref for cleanup
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  // Stop polling helper
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  // Start polling for a task (used both for new tasks and resuming)
  const startPollingForTask = useCallback((taskId: string) => {
    stopPolling()
    
    pollingRef.current = setInterval(async () => {
      try {
        const statusResponse = await apiClient.get<TaskStatusResponse>(
          `/api/alphas/tasks/${taskId}/status`
        )

        // Handle PROGRESS state with real progress info
        if (statusResponse.status === "PROGRESS") {
          const stepMap: Record<string, string> = {
            loading_data: "loading_data",
            computing_factors: "computing_factors",
            loading_model: "running_model",
            running_model: "running_model",
            generating_signals: "generating_signals",
            saving_signals: "generating_signals",
          }
          const step = stepMap[statusResponse.step || ""] || "running"
          
          setWorkflowStatus({
            step: step as WorkflowStatus["step"],
            progress: statusResponse.progress || 50,
            message: statusResponse.message || "Processing...",
            taskId,
          })
        } else if (statusResponse.status === "PENDING") {
          setWorkflowStatus({
            step: "queued",
            progress: 5,
            message: "Waiting for worker...",
            taskId,
          })
        } else if (statusResponse.status === "STARTED") {
          setWorkflowStatus({
            step: "running",
            progress: 10,
            message: "Task started...",
            taskId,
          })
        } else if (statusResponse.status === "SUCCESS") {
          stopPolling()
          const result = statusResponse.result as {
            signals_generated?: number
            batch_id?: string
            alpha_name?: string
          } | null

          setWorkflowStatus({
            step: "complete",
            progress: 100,
            message: `Generated ${result?.signals_generated || 0} trading signals`,
            taskId,
          })

          // Refresh signal history
          await fetchSignalHistory()
          setIsRunning(false)
        } else if (statusResponse.status === "FAILURE") {
          stopPolling()
          setWorkflowStatus({
            step: "error",
            progress: 0,
            message: "",
            error: statusResponse.error || "Task failed",
            taskId,
          })
          setIsRunning(false)
        } else if (statusResponse.status === "REVOKED") {
          stopPolling()
          setWorkflowStatus({
            step: "error",
            progress: 0,
            message: "",
            error: "Task was cancelled",
            taskId,
          })
          setIsRunning(false)
        }
      } catch (pollError) {
        console.error("Failed to poll task status:", pollError)
      }
    }, 1000)
  }, [fetchSignalHistory, stopPolling])

  // Check for existing active task on page load
  useEffect(() => {
    const checkForActiveTask = async () => {
      try {
        const response = await apiClient.get<TaskStatusResponse | null>(
          `/api/alphas/live/${alphaId}/current-task`
        )
        
        if (response && response.task_id) {
          // There's an active task, resume polling
          setIsRunning(true)
          
          // Set initial status from the response
          if (response.status === "PROGRESS" && response.step) {
            const stepMap: Record<string, string> = {
              loading_data: "loading_data",
              computing_factors: "computing_factors",
              loading_model: "running_model",
              running_model: "running_model",
              generating_signals: "generating_signals",
              saving_signals: "generating_signals",
            }
            setWorkflowStatus({
              step: (stepMap[response.step] || "running") as WorkflowStatus["step"],
              progress: response.progress || 50,
              message: response.message || "Processing...",
              taskId: response.task_id,
            })
          } else {
            setWorkflowStatus({
              step: "running",
              progress: 10,
              message: "Resuming task monitoring...",
              taskId: response.task_id,
            })
          }
          
          // Start polling
          startPollingForTask(response.task_id)
        }
      } catch (error) {
        // Silently ignore - no active task or API error
        console.debug("No active task found:", error)
      }
    }

    if (alphaId) {
      checkForActiveTask()
    }
  }, [alphaId, startPollingForTask])

  // Run workflow via Celery task
  const handleRunWorkflow = useCallback(async () => {
    if (!alpha) return

    setIsRunning(true)
    setCurrentSignals([])
    stopPolling()

    try {
      // Trigger the Celery task
      setWorkflowStatus({
        step: "queued",
        progress: 0,
        message: "Queuing signal generation task...",
      })

      const triggerResponse = await apiClient.post<{
        task_id: string
        status: string
        alpha_id: string | null
        message: string
      }>(`/api/alphas/live/${alphaId}/trigger-signals`)

      const taskId = triggerResponse.task_id

      setWorkflowStatus({
        step: "queued",
        progress: 5,
        message: triggerResponse.message,
        taskId,
      })

      // Start polling for task status (reuse shared function)
      startPollingForTask(taskId)

    } catch (error) {
      stopPolling()
      setWorkflowStatus({
        step: "error",
        progress: 0,
        message: "",
        error: error instanceof Error ? error.message : "Failed to start workflow",
      })
      setIsRunning(false)
    }
  }, [alpha, alphaId, stopPolling, startPollingForTask])

  // Execute single signal
  const handleExecuteSignal = useCallback(
    async (signalId: string) => {
      setExecutingSignals((prev) => new Set(prev).add(signalId))

      try {
        await apiClient.post(`/api/alphas/live/${alphaId}/signals/${signalId}/execute`, {})
        await fetchSignalHistory()
      } catch (error) {
        console.error("Failed to execute signal:", error)
      } finally {
        setExecutingSignals((prev) => {
          const next = new Set(prev)
          next.delete(signalId)
          return next
        })
      }
    },
    [alphaId, fetchSignalHistory]
  )

  // Execute all signals in batch
  const handleExecuteAll = useCallback(
    async (batchId: string) => {
      setExecutingSignals((prev) => new Set(prev).add(`batch-${batchId}`))

      try {
        await apiClient.post(`/api/alphas/live/${alphaId}/signals/execute-all`, {
          batch_id: batchId,
        })
        await fetchSignalHistory()
      } catch (error) {
        console.error("Failed to execute all signals:", error)
      } finally {
        setExecutingSignals((prev) => {
          const next = new Set(prev)
          next.delete(`batch-${batchId}`)
          return next
        })
      }
    },
    [alphaId, fetchSignalHistory]
  )

  // Loading state
  if (authLoading || !authUser || alphaLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0c0c0c] text-[#fafafa]">
        <Loader2 className="size-6 animate-spin text-white/60" />
      </div>
    )
  }

  if (!alpha) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0c0c0c] text-[#fafafa]">
        <p className="text-white/60">Alpha not found</p>
      </div>
    )
  }

  const factors = alpha.workflow_config.features || []
  const strategyParams = alpha.workflow_config.strategy?.params || {}

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
            tagline={alpha.hypothesis || "Generate trading signals from latest market data"}
            title={alpha.name}
            action={
              <Link href={`/dashboard/${username}/alphas/live`}>
                <Button
                  variant="outline"
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  <ArrowLeft className="mr-2 size-4" />
                  Back to Live Alphas
                </Button>
              </Link>
            }
          />

          {/* Alpha Overview */}
          <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
            <CardContent className="pt-6">
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
                <div>
                  <p className="text-xs text-white/50">Model Type</p>
                  <p className="mt-1 font-medium text-white">
                    {alpha.model_type || "LightGBM"}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-white/50">Strategy</p>
                  <p className="mt-1 font-medium text-white">{alpha.strategy_type}</p>
                </div>
                <div>
                  <p className="text-xs text-white/50">Top-K / N-Drop</p>
                  <p className="mt-1 font-medium text-white">
                    {strategyParams.topk || 30} / {strategyParams.n_drop || 5}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-white/50">Allocated Capital</p>
                  <p className="mt-1 font-medium text-white">
                    ₹{alpha.allocated_amount.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-white/50">Total Signals</p>
                  <p className="mt-1 font-medium text-white">{alpha.total_signals}</p>
                </div>
              </div>
              {factors.length > 0 && (
                <div className="mt-4 border-t border-white/10 pt-4">
                  <p className="text-xs text-white/50">Factors ({factors.length})</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {factors.slice(0, 8).map((f) => (
                      <span
                        key={f.name}
                        className="rounded-full bg-violet-500/20 px-2 py-0.5 text-xs text-violet-300"
                      >
                        {f.name}
                      </span>
                    ))}
                    {factors.length > 8 && (
                      <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/50">
                        +{factors.length - 8} more
                      </span>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Workflow and Current Signals */}
          <div className="grid gap-6 lg:grid-cols-2">
            <WorkflowStatusCard
              status={workflowStatus}
              onRunWorkflow={handleRunWorkflow}
              isRunning={isRunning}
            />

            <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                  <TrendingUp className="size-5 text-emerald-400" />
                  Current Run Signals
                </CardTitle>
                <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                  Signals from the latest workflow run
                </CardDescription>
              </CardHeader>
              <CardContent>
                <motion.div variants={listVariants} initial="hidden" animate="show">
                  <CurrentSignalsTable signals={currentSignals} loading={isRunning} />
                </motion.div>
              </CardContent>
            </Card>
          </div>

          {/* Signal History */}
          <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                  <Clock className="size-5 text-cyan-400" />
                  Signal History
                </CardTitle>
                <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                  Historical signals grouped by generation date
                </CardDescription>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={fetchSignalHistory}
                disabled={signalsLoading}
                className="text-white/60 hover:text-white"
              >
                <RefreshCw
                  className={cn("size-4", signalsLoading && "animate-spin")}
                />
              </Button>
            </CardHeader>
            <CardContent>
              <SignalHistoryTable
                batches={signalBatches}
                loading={signalsLoading}
                onExecuteSignal={handleExecuteSignal}
                onExecuteAll={handleExecuteAll}
                executingSignals={executingSignals}
              />
            </CardContent>
          </Card>
        </Container>
      </main>
    </div>
  )
}
