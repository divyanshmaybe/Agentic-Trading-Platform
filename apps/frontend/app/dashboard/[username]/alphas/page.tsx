"use client"

import React, { FormEvent, useState, useEffect, useCallback } from "react"
import { createPortal } from "react-dom"
import { AnimatePresence, motion, type Variants } from "framer-motion"
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Beaker,
  Check,
  ChevronRight,
  Copy,
  Eye,
  Loader2,
  Play,
  Plus,
  Rocket,
  Square,
  Trash2,
  TrendingUp,
  X,
  Zap,
} from "lucide-react"
import { useParams } from "next/navigation"
import Link from "next/link"

import { AlphaChat, AlphaGraph } from "@/components/alpha"
import { AgentOverview } from "@/components/agent/AgentOverview"
import { AgentTradesTable } from "@/components/agent/AgentTradesTable"
import { PortfolioSnapshots } from "@/components/portfolio/PortfolioSnapshots"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/hooks/useAuth"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"
import {
  useAlphas,
  useAlphaCopilotRuns,
  alphaToTopAlpha,
  type LiveAlpha,
  type AlphaCopilotRun,
  type AlphaCopilotResult,
} from "@/hooks/useAlphas"
import { cn } from "@/lib/utils"

// Tab types
type TabType = "research" | "live"

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

// =====================================================
// NEW HYPOTHESIS MODAL - Creates AlphaCopilot Runs
// =====================================================
type HypothesisForm = {
  hypothesis: string
  maxIterations: number
  numRuns: number
  modelType: string
  strategyType: string
  topk: number
  nDrop: number
  trainStartDate: string
  trainEndDate: string
  validationStartDate: string
  validationEndDate: string
  testStartDate: string
  testEndDate: string
  initialCapital: number
  commission: number
  slippage: number
  rebalanceFrequency: number
}

const defaultHypothesisForm: HypothesisForm = {
  hypothesis: "",
  maxIterations: 3,
  numRuns: 1,
  modelType: "LightGBM",
  strategyType: "TopkDropout",
  topk: 30,
  nDrop: 5,
  trainStartDate: "2022-01-01",
  trainEndDate: "2022-12-31",
  validationStartDate: "2023-01-01",
  validationEndDate: "2023-03-31",
  testStartDate: "2023-04-01",
  testEndDate: "2023-11-28",
  initialCapital: 1000000,
  commission: 0.001,
  slippage: 0.001,
  rebalanceFrequency: 1,
}

function NewHypothesisModal({
  open,
  onOpenChange,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (hypothesis: string, config: Record<string, unknown>) => Promise<void>
}) {
  const [form, setForm] = useState<HypothesisForm>(defaultHypothesisForm)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [currentRegime, setCurrentRegime] = useState<string | null>(null)
  const [regimeLoading, setRegimeLoading] = useState(false)

  // Fetch current regime when modal opens
  const fetchCurrentRegime = useCallback(async () => {
    setRegimeLoading(true)
    try {
      const PORTFOLIO_API_URL = process.env.NEXT_PUBLIC_PORTFOLIO_API_URL ?? "http://localhost:8000"
      
      // Get access token from cookie or localStorage
      const getAccessToken = (): string | null => {
        if (typeof window !== "undefined") {
          const cookies = document.cookie.split("; ")
          const entry = cookies
            .map((c) => c.trim())
            .find((section) => section.startsWith("access_token="))
          if (entry) {
            const [, value] = entry.split("=")
            return value ? decodeURIComponent(value) : null
          }
          return localStorage.getItem("access_token")
        }
        return null
      }

      const token = getAccessToken()
      if (!token) {
        console.warn("No access token available for regime fetch")
        return
      }

      const response = await fetch(`${PORTFOLIO_API_URL}/api/regime/current`, {
        method: "GET",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setCurrentRegime(data.regime)
      } else {
        console.warn("Failed to fetch current regime:", response.statusText)
      }
    } catch (err) {
      console.error("Error fetching current regime:", err)
    } finally {
      setRegimeLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      fetchCurrentRegime()
    }
  }, [open, fetchCurrentRegime])

  const resetState = () => {
    setForm(defaultHypothesisForm)
    setSubmitting(false)
    setError(null)
    setShowAdvanced(false)
    setCurrentRegime(null)
  }

  const handleClose = () => {
    resetState()
    onOpenChange(false)
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!form.hypothesis.trim()) return

    setSubmitting(true)
    setError(null)

    try {
      // Append current regime to hypothesis if available
      let hypothesisWithRegime = form.hypothesis.trim()
      if (currentRegime) {
        hypothesisWithRegime = `${hypothesisWithRegime}\n\n[Current Market Regime: ${currentRegime}]`
      }

      await onSubmit(hypothesisWithRegime, {
        max_iterations: form.maxIterations,
        num_runs: form.numRuns,
        model_type: form.modelType,
        strategy_type: form.strategyType,
        topk: form.topk,
        n_drop: form.nDrop,
        train_start_date: form.trainStartDate,
        train_end_date: form.trainEndDate,
        validation_start_date: form.validationStartDate,
        validation_end_date: form.validationEndDate,
        test_start_date: form.testStartDate,
        test_end_date: form.testEndDate,
        initial_capital: form.initialCapital,
        commission: form.commission,
        slippage: form.slippage,
        rebalance_frequency: form.rebalanceFrequency,
      })
      handleClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create run")
    } finally {
      setSubmitting(false)
    }
  }

  if (typeof window === "undefined") return null

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/70 backdrop-blur"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 260, damping: 26 }}
            className="mx-4 max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-black/90 p-6 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
                  <Beaker className="size-5 text-violet-400" />
                  Run Alpha Research
                </h2>
                <p className="mt-1 text-sm text-white/60">
                  Describe your trading hypothesis and let AI generate factor expressions.
                </p>
              </div>
              <button
                type="button"
                onClick={handleClose}
                className="rounded-full border border-white/10 bg-white/5 p-1.5 text-white/70 transition hover:bg-white/10 hover:text-white"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* Current Market Regime Indicator */}
            <div className="mt-4 space-y-2">
              <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                <TrendingUp className="size-4 text-cyan-400" />
                <span className="text-xs text-white/60">Current Market Regime:</span>
                {regimeLoading ? (
                  <Loader2 className="size-3 animate-spin text-white/40" />
                ) : currentRegime ? (
                  <span className="text-xs font-medium text-cyan-300">{currentRegime}</span>
                ) : (
                  <span className="text-xs text-white/40">Unable to detect</span>
                )}
                <span className="ml-auto text-xs text-white/40">(will be appended to hypothesis)</span>
              </div>
              
              {/* Sideways Market Warning */}
              {currentRegime && currentRegime.toLowerCase().includes("sideways") && (
                <div className="flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2">
                  <X className="mt-0.5 size-4 shrink-0 text-rose-400" />
                  <p className="text-xs text-rose-300">
                    <span className="font-semibold">Warning:</span> Alphas are not suitable for sideways markets. 
                    Consider waiting for a trending market regime for better performance.
                  </p>
                </div>
              )}
            </div>

            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              {/* Hypothesis Input */}
              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wide text-white/50">
                  Trading Hypothesis
                </label>
                <textarea
                  value={form.hypothesis}
                  onChange={(e) => setForm((prev) => ({ ...prev, hypothesis: e.target.value }))}
                  required
                  rows={4}
                  placeholder="Example: Stocks with strong momentum and low volatility tend to outperform. Look for stocks breaking out of consolidation patterns with increasing volume..."
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                />
              </div>

              {/* Quick Settings */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wide text-white/50">
                    Iterations
                  </label>
                  <select
                    value={form.maxIterations}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, maxIterations: parseInt(e.target.value) }))
                    }
                    className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                  >
                    <option value="1">1 iteration (quick test)</option>
                    <option value="3">3 iterations (recommended)</option>
                    <option value="5">5 iterations (thorough)</option>
                    <option value="10">10 iterations (extensive)</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wide text-white/50">
                    Parallel Runs
                  </label>
                  <select
                    value={form.numRuns}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, numRuns: parseInt(e.target.value) }))
                    }
                    className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                  >
                    <option value="1">1 run</option>
                    <option value="2">2 parallel runs</option>
                    <option value="3">3 parallel runs</option>
                  </select>
                </div>
              </div>

              {/* Advanced Settings Toggle */}
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-2 text-xs text-white/50 hover:text-white/70"
              >
                <ChevronRight
                  className={cn("size-4 transition-transform", showAdvanced && "rotate-90")}
                />
                Advanced Settings
              </button>

              {/* Advanced Settings */}
              <AnimatePresence>
                {showAdvanced && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="space-y-4 overflow-hidden"
                  >
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          Model Type
                        </label>
                        <select
                          value={form.modelType}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, modelType: e.target.value }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        >
                          <option value="LightGBM">LightGBM</option>
                          <option value="XGBoost">XGBoost</option>
                          <option value="Linear">Linear</option>
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          Strategy
                        </label>
                        <select
                          value={form.strategyType}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, strategyType: e.target.value }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        >
                          <option value="TopkDropout">Top-K Dropout</option>
                          <option value="WeightedTopk">Weighted Top-K</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          Top-K Stocks
                        </label>
                        <input
                          type="number"
                          value={form.topk}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, topk: parseInt(e.target.value) || 30 }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          N-Drop
                        </label>
                        <input
                          type="number"
                          value={form.nDrop}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, nDrop: parseInt(e.target.value) || 5 }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        />
                      </div>
                    </div>

                    {/* Date Periods */}
                    <div className="space-y-3">
                      <p className="text-xs font-medium uppercase tracking-wide text-white/40">
                        Date Periods
                      </p>
                      <div className="space-y-2">
                        <div className="flex items-center gap-3">
                          <span className="w-24 shrink-0 text-xs text-white/50">Train</span>
                          <input
                            type="date"
                            value={form.trainStartDate}
                            onChange={(e) =>
                              setForm((prev) => ({ ...prev, trainStartDate: e.target.value }))
                            }
                            className="flex-1 rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                          />
                          <span className="text-white/30">→</span>
                          <input
                            type="date"
                            value={form.trainEndDate}
                            onChange={(e) =>
                              setForm((prev) => ({ ...prev, trainEndDate: e.target.value }))
                            }
                            className="flex-1 rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                          />
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="w-24 shrink-0 text-xs text-white/50">Validation</span>
                          <input
                            type="date"
                            value={form.validationStartDate}
                            onChange={(e) =>
                              setForm((prev) => ({ ...prev, validationStartDate: e.target.value }))
                            }
                            className="flex-1 rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                          />
                          <span className="text-white/30">→</span>
                          <input
                            type="date"
                            value={form.validationEndDate}
                            onChange={(e) =>
                              setForm((prev) => ({ ...prev, validationEndDate: e.target.value }))
                            }
                            className="flex-1 rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                          />
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="w-24 shrink-0 text-xs text-white/50">Test</span>
                          <input
                            type="date"
                            value={form.testStartDate}
                            onChange={(e) =>
                              setForm((prev) => ({ ...prev, testStartDate: e.target.value }))
                            }
                            className="flex-1 rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                          />
                          <span className="text-white/30">→</span>
                          <input
                            type="date"
                            value={form.testEndDate}
                            onChange={(e) =>
                              setForm((prev) => ({ ...prev, testEndDate: e.target.value }))
                            }
                            className="flex-1 rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Backtest Configuration */}
                    <div className="grid grid-cols-4 gap-4">
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          Initial Capital
                        </label>
                        <input
                          type="number"
                          value={form.initialCapital}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, initialCapital: parseInt(e.target.value) || 1000000 }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          Commission
                        </label>
                        <input
                          type="number"
                          step="0.0001"
                          value={form.commission}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, commission: parseFloat(e.target.value) || 0.001 }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          Slippage
                        </label>
                        <input
                          type="number"
                          step="0.0001"
                          value={form.slippage}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, slippage: parseFloat(e.target.value) || 0.001 }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-white/50">
                          Rebalance Freq
                        </label>
                        <input
                          type="number"
                          min="1"
                          value={form.rebalanceFrequency}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, rebalanceFrequency: parseInt(e.target.value) || 1 }))
                          }
                          className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-400/50"
                        />
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {error && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                  {error}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleClose}
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  className="border border-violet-500/40 bg-violet-500/20 text-violet-100 hover:bg-violet-500/30"
                  disabled={submitting || !form.hypothesis.trim()}
                >
                  {submitting ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      Starting...
                    </>
                  ) : (
                    <>
                      <Zap className="mr-2 size-4" />
                      Start Research
                    </>
                  )}
                </Button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  )
}

// =====================================================
// DEPLOY ALPHA MODAL - Deploy to Live Trading
// =====================================================
function DeployAlphaModal({
  open,
  onOpenChange,
  run,
  onDeploy,
  alphaData,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  run: AlphaCopilotRun | null
  onDeploy: (name: string, amount: number) => Promise<void>
  alphaData: ReturnType<typeof useAgentDashboard>["data"]
}) {
  const [name, setName] = useState("")
  const [amount, setAmount] = useState(100000)
  const [deploying, setDeploying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleClose = () => {
    setName("")
    setAmount(100000)
    setDeploying(false)
    setError(null)
    onOpenChange(false)
  }

  const handleDeploy = async () => {
    if (!name.trim() || amount <= 0) return

    // Validate that allocated capital is less than or equal to available cash
    const availableCash = parseFloat(alphaData?.allocation?.available_cash || "0")
    if (amount > availableCash) {
      setError(`Allocated capital (₹${amount.toLocaleString()}) cannot exceed available cash (₹${availableCash.toLocaleString()})`)
      return
    }

    setDeploying(true)
    setError(null)

    try {
      await onDeploy(name, amount)
      handleClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to deploy")
    } finally {
      setDeploying(false)
    }
  }

  if (typeof window === "undefined" || !run) return null

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/70 backdrop-blur"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 260, damping: 26 }}
            className="mx-4 w-full max-w-lg rounded-2xl border border-white/10 bg-black/90 p-6 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
                  <Rocket className="size-5 text-emerald-400" />
                  Deploy Alpha to Live
                </h2>
                <p className="mt-1 text-sm text-white/60">
                  This will start generating daily trading signals.
                </p>
              </div>
              <button
                type="button"
                onClick={handleClose}
                className="rounded-full border border-white/10 bg-white/5 p-1.5 text-white/70 transition hover:bg-white/10 hover:text-white"
              >
                <X className="size-4" />
              </button>
            </div>

            <div className="mt-6 space-y-4">
              <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-wide text-white/50">From Research Run</p>
                <p className="mt-1 line-clamp-2 text-sm text-white">
                  {run.hypothesis.slice(0, 100)}...
                </p>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wide text-white/50">Alpha Name</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Momentum Breakout Strategy"
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                />
              </div>

              {/* Available Cash Display */}
              <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs uppercase tracking-wide text-white/50">
                    Available Cash
                  </span>
                  <span className="text-sm font-semibold text-cyan-300">
                    ₹{parseFloat(alphaData?.allocation?.available_cash || "0").toLocaleString()}
                  </span>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wide text-white/50">
                  Allocated Capital (₹)
                </label>
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(parseInt(e.target.value) || 0)}
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                />
                <p className="text-xs text-white/50">
                  Must be less than or equal to available cash
                </p>
              </div>

              {error && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                  {error}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleClose}
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleDeploy}
                  className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
                  disabled={deploying || !name.trim() || amount <= 0}
                >
                  {deploying ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      Deploying...
                    </>
                  ) : (
                    <>
                      <Rocket className="mr-2 size-4" />
                      Deploy Alpha
                    </>
                  )}
                </Button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  )
}

// =====================================================
// VIEW RESULTS MODAL - Show factors and metrics
// =====================================================
function ResultsModal({
  open,
  onOpenChange,
  run,
  results,
  loading,
  onDeploy,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  run: AlphaCopilotRun | null
  results: AlphaCopilotResult | null
  loading: boolean
  onDeploy: () => void
}) {
  const [copiedFactor, setCopiedFactor] = useState<string | null>(null)

  const handleCopyFactor = (expression: string, name: string) => {
    navigator.clipboard.writeText(expression)
    setCopiedFactor(name)
    setTimeout(() => setCopiedFactor(null), 2000)
  }

  if (typeof window === "undefined" || !run) return null

  // Use factors from run.generated_factors (primary) or fallback to results
  const allFactors = (run.generated_factors || results?.all_factors || []) as Array<{
    name?: string
    expression?: string
    description?: string
  }>
  const bestFactors = (run.best_factors || results?.best_factors || []) as Array<{
    name?: string
    expression?: string
  }>
  
  // Check if a factor is Best (best performing from the run)
  // If no best_factors, mark all factors from the final iteration as best (since the workflow always picks a best iteration)
  const isSOTA = (factorName: string) => {
    if (bestFactors.length > 0) {
      return bestFactors.some(bf => bf.name === factorName)
    }
    // If no best_factors specified, all generated factors are considered best (from the winning iteration)
    return allFactors.length > 0
  }
  
  // Calculate best factors count
  const sotaCount = bestFactors.length > 0 ? bestFactors.length : allFactors.length
  
  // Sort factors to show best factors first
  const factors = [...allFactors].sort((a, b) => {
    const aIsSOTA = isSOTA(a.name || "")
    const bIsSOTA = isSOTA(b.name || "")
    if (aIsSOTA && !bIsSOTA) return -1
    if (!aIsSOTA && bIsSOTA) return 1
    return 0
  })
  
  const metrics = results?.final_metrics as Record<string, unknown> | null

  // Helper to safely extract metric from nested or flat structure
  const getMetric = (key: string): number | string => {
    if (!metrics) return "N/A"
    if (key in metrics && metrics[key] != null) return metrics[key] as number | string
    const train = metrics.train as Record<string, unknown> | undefined
    if (train && key in train && train[key] != null) return train[key] as number | string
    return "N/A"
  }

  // Extract key metrics
  const sharpeRatio = getMetric("sharpe_ratio")
  const totalReturn = getMetric("total_return")
  const annualReturn = getMetric("annual_return")
  const maxDrawdown = getMetric("max_drawdown")
  const winRate = getMetric("win_rate")

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/70 backdrop-blur"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 260, damping: 26 }}
            className="mx-4 max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-white/10 bg-black/90 shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-4 border-b border-white/10 p-6">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
                  <TrendingUp className="size-5 text-cyan-400" />
                  Research Results
                </h2>
                <p className="mt-1 line-clamp-1 text-sm text-white/60">
                  {run.hypothesis}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className="rounded-full border border-white/10 bg-white/5 p-1.5 text-white/70 transition hover:bg-white/10 hover:text-white"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* Content */}
            <div className="max-h-[calc(85vh-180px)] overflow-y-auto p-6">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="size-6 animate-spin text-white/40" />
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Metrics Grid */}
                  <div>
                    <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-white/50">
                      Performance Metrics
                    </h3>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs text-white/50">Sharpe Ratio</p>
                        <p className="mt-1 text-lg font-semibold text-white">
                          {typeof sharpeRatio === "number" ? sharpeRatio.toFixed(2) : sharpeRatio}
                        </p>
                      </div>
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs text-white/50">Total Return</p>
                        <p className="mt-1 text-lg font-semibold text-emerald-400">
                          {typeof totalReturn === "number"
                            ? `${(totalReturn * 100).toFixed(1)}%`
                            : totalReturn}
                        </p>
                      </div>
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs text-white/50">Annual Return</p>
                        <p className="mt-1 text-lg font-semibold text-white">
                          {typeof annualReturn === "number"
                            ? `${(annualReturn * 100).toFixed(1)}%`
                            : annualReturn}
                        </p>
                      </div>
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs text-white/50">Max Drawdown</p>
                        <p className="mt-1 text-lg font-semibold text-rose-400">
                          {typeof maxDrawdown === "number"
                            ? `${(maxDrawdown * 100).toFixed(1)}%`
                            : maxDrawdown}
                        </p>
                      </div>
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs text-white/50">Win Rate</p>
                        <p className="mt-1 text-lg font-semibold text-white">
                          {typeof winRate === "number" ? `${(winRate * 100).toFixed(0)}%` : winRate}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Generated Factors */}
                  <div>
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-white/50">
                      Generated Factors ({factors.length})
                      {bestFactors.length > 0 && (
                        <span className="text-xs normal-case text-amber-400">• {bestFactors.length} Best</span>
                      )}
                    </h3>
                    {factors.length === 0 ? (
                      <p className="text-sm text-white/40">No factors generated</p>
                    ) : (
                      <div className="space-y-2">
                        {factors.map((factor, idx) => {
                          const factorName = (factor as Record<string, unknown>).name as string
                          const sota = isSOTA(factorName)
                          return (
                            <div
                              key={idx}
                              className={`rounded-xl border p-3 ${
                                sota
                                  ? "border-amber-500/40 bg-amber-500/10"
                                  : "border-white/10 bg-white/5"
                              }`}
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <p className={`text-sm font-medium ${
                                      sota ? "text-amber-300" : "text-cyan-300"
                                    }`}>
                                      {factorName}
                                    </p>
                                    {sota && (
                                      <span className="flex items-center gap-1 rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-300">
                                        <TrendingUp className="size-3" />
                                        Best
                                      </span>
                                    )}
                                  </div>
                                  <code className="mt-1 block break-all text-xs text-white/70">
                                    {(factor as Record<string, unknown>).expression as string}
                                  </code>
                                  {(factor as Record<string, unknown>).description ? (
                                    <p className="mt-2 text-xs text-white/50">
                                      {String((factor as Record<string, unknown>).description)}
                                    </p>
                                  ) : null}
                                </div>
                                <button
                                  onClick={() =>
                                    handleCopyFactor(
                                      (factor as Record<string, unknown>).expression as string,
                                      factorName
                                    )
                                  }
                                  className="shrink-0 rounded-lg border border-white/10 bg-white/5 p-1.5 text-white/50 transition hover:bg-white/10 hover:text-white"
                                  title="Copy expression"
                                >
                                  {copiedFactor === factorName ? (
                                    <Check className="size-3.5 text-emerald-400" />
                                  ) : (
                                    <Copy className="size-3.5" />
                                  )}
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>

                  {/* Config Summary */}
                  {results?.workflow_config && (
                    <div>
                      <h3 className="mb-3 text-sm font-medium uppercase tracking-wide text-white/50">
                        Workflow Configuration
                      </h3>
                      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                          <div>
                            <span className="text-white/50">Model:</span>{" "}
                            <span className="text-white">
                              {(results.workflow_config.model as Record<string, unknown>)?.type as string || "Direct Factors"}
                            </span>
                          </div>
                          <div>
                            <span className="text-white/50">Strategy:</span>{" "}
                            <span className="text-white">
                              {(results.workflow_config.strategy as Record<string, unknown>)?.type as string || "TopkDropout"}
                            </span>
                          </div>
                          <div>
                            <span className="text-white/50">Features:</span>{" "}
                            <span className="text-white">
                              {(results.workflow_config.features as unknown[])?.length || 0}
                            </span>
                          </div>
                          <div>
                            <span className="text-white/50">Iterations:</span>{" "}
                            <span className="text-white">{run.current_iteration}/{run.num_iterations}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-end gap-2 border-t border-white/10 p-4">
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                className="border-white/20 text-white hover:bg-white/10"
              >
                Close
              </Button>
              {run.status.toLowerCase() === "completed" && (
                <Button
                  onClick={onDeploy}
                  className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
                >
                  <Rocket className="mr-2 size-4" />
                  Deploy to Live
                </Button>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  )
}

// =====================================================
// RESEARCH RUNS COMPONENT
// =====================================================
function ResearchRuns({
  runs,
  loading,
  onDeploy,
  onViewResults,
}: {
  runs: AlphaCopilotRun[]
  loading: boolean
  onDeploy: (run: AlphaCopilotRun) => void
  onViewResults: (run: AlphaCopilotRun) => void
}) {
  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case "completed":
        return (
          <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">
            <Check className="size-3" /> Completed
          </span>
        )
      case "running":
        return (
          <span className="flex items-center gap-1 rounded-full bg-blue-500/15 px-2 py-0.5 text-xs text-blue-300">
            <Loader2 className="size-3 animate-spin" /> Running
          </span>
        )
      case "failed":
        return (
          <span className="flex items-center gap-1 rounded-full bg-rose-500/15 px-2 py-0.5 text-xs text-rose-300">
            <X className="size-3" /> Failed
          </span>
        )
      default:
        return (
          <span className="flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/60">
            {status}
          </span>
        )
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-white/40" />
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Beaker className="size-12 text-white/20" />
        <p className="mt-4 text-sm text-white/60">No research runs yet</p>
        <p className="mt-1 text-xs text-white/40">
          Click &quot;New Research&quot; to start generating alpha factors
        </p>
      </div>
    )
  }

  return (
    <motion.div variants={listVariants} initial="hidden" animate="show" className="space-y-3">
      {runs.map((run) => (
        <motion.div
          key={run.id}
          variants={itemVariants}
          className="rounded-xl border border-white/10 bg-black/25 p-4"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="line-clamp-2 text-sm text-white">{run.hypothesis}</p>
              <div className="mt-2 flex items-center gap-3 text-xs text-white/50">
                <span>
                  Iteration {run.current_iteration}/{run.num_iterations}
                </span>
                <span>•</span>
                <span>{new Date(run.created_at).toLocaleDateString()}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {getStatusBadge(run.status)}
              {(run.status.toLowerCase() === "completed" || run.status.toLowerCase() === "failed") && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onViewResults(run)}
                  className="border-cyan-500/30 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20"
                >
                  <Eye className="mr-1 size-3" />
                  Results
                </Button>
              )}
              {run.status.toLowerCase() === "completed" && (
                <Button
                  size="sm"
                  onClick={() => onDeploy(run)}
                  className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
                >
                  <Rocket className="mr-1 size-3" />
                  Deploy
                </Button>
              )}
            </div>
          </div>

          {/* Progress bar for running */}
          {run.status.toLowerCase() === "running" && (
            <div className="mt-3">
              <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                <motion.div
                  className="h-full bg-blue-500"
                  initial={{ width: 0 }}
                  animate={{
                    width: `${(run.current_iteration / run.num_iterations) * 100}%`,
                  }}
                  transition={{ duration: 0.5 }}
                />
              </div>
            </div>
          )}
        </motion.div>
      ))}
    </motion.div>
  )
}

// =====================================================
// LIVE ALPHAS COMPONENT
// =====================================================
function LiveAlphasList({
  alphas,
  loading,
  onStart,
  onStop,
  onDelete,
  username,
}: {
  alphas: LiveAlpha[]
  loading: boolean
  onStart: (id: string) => Promise<LiveAlpha | void>
  onStop: (id: string) => Promise<LiveAlpha | void>
  onDelete: (id: string) => Promise<void>
  username: string
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-white/40" />
      </div>
    )
  }

  if (alphas.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Rocket className="size-12 text-white/20" />
        <p className="mt-4 text-sm text-white/60">No live alphas deployed</p>
        <p className="mt-1 text-xs text-white/40">
          Complete a research run and deploy it to start live trading
        </p>
      </div>
    )
  }

  return (
    <motion.div variants={listVariants} initial="hidden" animate="show" className="space-y-3">
      {alphas.map((alpha) => {
        const display = alphaToTopAlpha(alpha)
        const isRunning = alpha.status === "running"
        const Icon = display.direction === "up" ? ArrowUpRight : ArrowDownRight

        return (
          <motion.div
            key={alpha.id}
            variants={itemVariants}
            className="rounded-xl border border-white/10 bg-black/25 p-4"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-white">{alpha.name}</p>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs",
                      isRunning
                        ? "bg-emerald-500/15 text-emerald-300"
                        : "bg-white/10 text-white/50"
                    )}
                  >
                    {isRunning ? "Running" : "Stopped"}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-4 text-xs text-white/50">
                  <span>₹{alpha.allocated_amount.toLocaleString()}</span>
                  <span>•</span>
                  <span>{alpha.total_signals} signals</span>
                  <span>•</span>
                  <span>{alpha.strategy_type}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium",
                    display.direction === "up"
                      ? "bg-emerald-500/15 text-emerald-200"
                      : "bg-rose-500/15 text-rose-200"
                  )}
                >
                  <Icon className="size-4" />
                  {display.returnPct > 0 ? "+" : ""}
                  {display.returnPct.toFixed(1)}%
                </span>
              </div>
            </div>

            <div className="mt-3 flex items-center gap-2">
              {isRunning ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onStop(alpha.id)}
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  <Square className="mr-1 size-3" />
                  Stop
                </Button>
              ) : (
                <Button
                  size="sm"
                  onClick={() => onStart(alpha.id)}
                  className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
                >
                  <Play className="mr-1 size-3" />
                  Start
                </Button>
              )}
              <Link href={`/dashboard/${username}/alphas/live/${alpha.id}`}>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/10"
                >
                  <ArrowRight className="mr-1 size-3" />
                  Details
                </Button>
              </Link>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onDelete(alpha.id)}
                className="border-rose-500/30 text-rose-300 hover:bg-rose-500/10"
              >
                <Trash2 className="size-3" />
              </Button>
            </div>
          </motion.div>
        )
      })}
    </motion.div>
  )
}

// =====================================================
// MAIN PAGE COMPONENT
// =====================================================
export default function AlphasPage() {
  const params = useParams()
  const username = params.username as string
  const [activeTab, setActiveTab] = useState<TabType>("research")
  const [hypothesisModalOpen, setHypothesisModalOpen] = useState(false)
  const [deployModalOpen, setDeployModalOpen] = useState(false)
  const [resultsModalOpen, setResultsModalOpen] = useState(false)
  const [selectedRun, setSelectedRun] = useState<AlphaCopilotRun | null>(null)
  const [selectedResults, setSelectedResults] = useState<AlphaCopilotResult | null>(null)
  const [resultsLoading, setResultsLoading] = useState(false)
  const [triggeringAgent, setTriggeringAgent] = useState(false)
  const [runResults, setRunResults] = useState<Record<string, AlphaCopilotResult>>({})

  // Auth
  const { user: authUser, loading: authLoading } = useAuth()
  
  // Agent dashboard data
  const {
    data: alphaData,
    loading: alphaLoading,
    isAllocating: alphaAllocating,
  } = useAgentDashboard("alpha")

  // AlphaCopilot runs
  const {
    runs,
    loading: runsLoading,
    createRun,
    getRunResults,
  } = useAlphaCopilotRuns()

  // Fetch results for completed runs with best_factors
  useEffect(() => {
    const fetchRunResults = async () => {
      const completedRuns = runs.filter(
        r => r.status.toLowerCase() === "completed" && r.best_factors && r.best_factors.length > 0
      )
      
      for (const run of completedRuns) {
        if (!runResults[run.id]) {
          try {
            const results = await getRunResults(run.id)
            setRunResults(prev => ({ ...prev, [run.id]: results }))
          } catch (error) {
            console.error(`Failed to fetch results for run ${run.id}:`, error)
          }
        }
      }
    }

    if (runs.length > 0 && !runsLoading) {
      fetchRunResults()
    }
  }, [runs, runsLoading])

  // Live alphas
  const {
    alphas,
    loading: alphasLoading,
    createAlpha,
    startAlpha,
    stopAlpha,
    deleteAlpha,
  } = useAlphas()

  // Handle creating a new research run
  const handleCreateRun = async (hypothesis: string, config: Record<string, unknown>) => {
    await createRun(hypothesis, config)
  }

  // Handle viewing results for a run
  const handleViewResults = async (run: AlphaCopilotRun) => {
    setSelectedRun(run)
    setResultsModalOpen(true)
    
    // Use cached results if available, otherwise fetch
    if (runResults[run.id]) {
      setSelectedResults(runResults[run.id])
      setResultsLoading(false)
    } else {
      setResultsLoading(true)
      setSelectedResults(null)
      try {
        const results = await getRunResults(run.id)
        setRunResults(prev => ({ ...prev, [run.id]: results }))
        setSelectedResults(results)
      } catch (error) {
        console.error("Failed to fetch results:", error)
      } finally {
        setResultsLoading(false)
      }
    }
  }

  // Handle deploying an alpha
  const handleDeployAlpha = async (name: string, amount: number) => {
    if (!selectedRun) return

    // Use cached results if available, otherwise fetch
    let results = runResults[selectedRun.id]
    if (!results) {
      results = await getRunResults(selectedRun.id)
      setRunResults(prev => ({ ...prev, [selectedRun.id]: results }))
    }

    await createAlpha({
      name,
      run_id: selectedRun.id,
      hypothesis: selectedRun.hypothesis,
      workflow_config: results.workflow_config || {},
      symbols: [], // Will be populated from workflow config
      allocated_amount: amount,
      portfolio_id: alphaData?.portfolio_id || "",
      model_type: (selectedRun.config as Record<string, unknown>).model_type as string,
      strategy_type: (selectedRun.config as Record<string, unknown>).strategy_type as string,
    })
  }

  // Handle triggering alpha agent
  const handleTriggerAgent = async () => {
    setTriggeringAgent(true)
    try {
      const authServerUrl = process.env.NEXT_PUBLIC_AUTH_BASE_URL 
        ? process.env.NEXT_PUBLIC_AUTH_BASE_URL.replace("/api/auth", "")
        : "http://localhost:4000"
      
      // Get auth token
      let token: string | null = null
      if (typeof window !== "undefined") {
        const match = document.cookie.match(/(^| )access_token=([^;]+)/)
        token = match ? match[2] : localStorage.getItem("access_token")
      }

      const headers: HeadersInit = {
        "Content-Type": "application/json",
      }
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
      }

      const response = await fetch(`${authServerUrl}/api/user/subscriptions`, {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({
          action: "subscribe",
          agent: "alpha",
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.message || data.error || "Failed to trigger alpha agent")
      }

      // Show success message or handle as needed
      alert("Alpha agent triggered successfully!")
    } catch (error) {
      console.error("Failed to trigger alpha agent:", error)
      alert(error instanceof Error ? error.message : "Failed to trigger alpha agent")
    } finally {
      setTriggeringAgent(false)
    }
  }

  // Show loading state while auth is being verified
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

      <main className="lg:pr-96">
        <Container className="no-scrollbar max-w-10xl space-y-6 py-8 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto">
          <PageHeading
            tagline="Research hypotheses, generate factors, and deploy winning alphas."
            title="Alpha Command Center"
            action={
              <div className="flex gap-2">
                <Link href={`/dashboard/${username}/alphas/live`}>
                  <Button
                    variant="outline"
                    className="border-cyan-500/40 bg-cyan-500/20 text-cyan-100 hover:bg-cyan-500/30"
                  >
                    <Zap className="mr-2 size-4" />
                    Live Signals
                  </Button>
                </Link>
                <Button
                  onClick={handleTriggerAgent}
                  disabled={triggeringAgent}
                  className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
                >
                  {triggeringAgent ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      Triggering...
                    </>
                  ) : (
                    <>
                      <Play className="mr-2 size-4" />
                      Trigger Alpha Agent
                    </>
                  )}
                </Button>
                <Button
                  onClick={() => setHypothesisModalOpen(true)}
                  className="border border-violet-500/40 bg-violet-500/20 text-violet-100 hover:bg-violet-500/30"
                >
                  <Plus className="mr-2 size-4" />
                  New Research
                </Button>
              </div>
            }
          />

          {/* Tabs */}
          <div className="flex gap-2">
            <button
              onClick={() => setActiveTab("research")}
              className={cn(
                "flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition",
                activeTab === "research"
                  ? "bg-violet-500/20 text-violet-200"
                  : "text-white/60 hover:bg-white/5 hover:text-white"
              )}
            >
              <Beaker className="size-4" />
              Research Runs
              {runs.length > 0 && (
                <span className="rounded-full bg-violet-500/30 px-2 py-0.5 text-xs">
                  {runs.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("live")}
              className={cn(
                "flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition",
                activeTab === "live"
                  ? "bg-emerald-500/20 text-emerald-200"
                  : "text-white/60 hover:bg-white/5 hover:text-white"
              )}
            >
              <Rocket className="size-4" />
              Live Alphas
              {alphas.filter((a) => a.status === "running").length > 0 && (
                <span className="rounded-full bg-emerald-500/30 px-2 py-0.5 text-xs">
                  {alphas.filter((a) => a.status === "running").length} active
                </span>
              )}
            </button>
          </div>

          <div className="flex flex-col gap-6">
            {/* Main Content Area */}
            <div className="grid gap-6 lg:grid-cols-2">
              {/* Left: Agent Overview or Research Runs */}
              <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                    {activeTab === "research" ? (
                      <>
                        <Beaker className="size-5 text-violet-400" />
                        Research Runs
                      </>
                    ) : (
                      <>
                        <Rocket className="size-5 text-emerald-400" />
                        Live Alphas
                      </>
                    )}
                  </CardTitle>
                  <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                    {activeTab === "research"
                      ? "AI-generated factor expressions from your hypotheses"
                      : "Deployed alphas generating daily signals"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="max-h-[400px] overflow-y-auto">
                  {activeTab === "research" ? (
                    <ResearchRuns
                      runs={runs}
                      loading={runsLoading}
                      onDeploy={(run) => {
                        setSelectedRun(run)
                        setDeployModalOpen(true)
                      }}
                      onViewResults={handleViewResults}
                    />
                  ) : (
                    <LiveAlphasList
                      alphas={alphas}
                      loading={alphasLoading}
                      onStart={startAlpha}
                      onStop={stopAlpha}
                      onDelete={deleteAlpha}
                      username={username}
                    />
                  )}
                </CardContent>
              </Card>

              {/* Right: Agent Overview */}
              <AgentOverview
                data={alphaData}
                loading={alphaLoading}
                isAllocating={alphaAllocating}
              />
            </div>

            {/* Best Factors Table - Only shown for Research tab */}
            {activeTab === "research" && runs.some(r => r.status.toLowerCase() === "completed" && r.best_factors && r.best_factors.length > 0) && (
              <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-xl text-[#fafafa]">
                    <TrendingUp className="size-5 text-amber-400" />
                    Best Factors
                  </CardTitle>
                  <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                    Best performing factors from completed research runs
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-6">
                    {runs
                      .filter(r => r.status.toLowerCase() === "completed" && r.best_factors && r.best_factors.length > 0)
                      .slice(0, 5)
                      .map(run => {
                        // Get actual results for this run
                        const results = runResults[run.id]
                        const metrics = results?.final_metrics as Record<string, unknown> | undefined
                        
                        // Extract test metrics (final_metrics contains test data)
                        const sharpe = typeof metrics?.sharpe_ratio === 'number' ? metrics.sharpe_ratio : 0
                        const ic = typeof metrics?.IC === 'number' ? metrics.IC : 0
                        const annualReturn = typeof metrics?.annual_return === 'number' ? metrics.annual_return : 0
                        const maxDrawdown = typeof metrics?.max_drawdown === 'number' ? metrics.max_drawdown : 0
                        
                        return (
                          <div key={run.id} className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                            {/* Run Header */}
                            <div className="mb-4 flex items-start justify-between gap-4">
                              <div className="min-w-0 flex-1">
                                <p className="text-sm font-medium text-white/80">{run.hypothesis}</p>
                                <p className="mt-1 text-xs text-white/50">
                                  {new Date(run.created_at).toLocaleDateString()} • {(run.best_factors || []).length} factors
                                </p>
                              </div>
                              <div className="flex shrink-0 gap-2">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => handleViewResults(run)}
                                  className="h-8 border-cyan-500/30 bg-cyan-500/10 px-3 text-xs text-cyan-300 hover:bg-cyan-500/20"
                                >
                                  <Eye className="mr-1.5 size-3" />
                                  View
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => {
                                    setSelectedRun(run)
                                    setDeployModalOpen(true)
                                  }}
                                  className="h-8 border-emerald-500/30 bg-emerald-500/10 px-3 text-xs text-emerald-300 hover:bg-emerald-500/20"
                                >
                                  <Rocket className="mr-1.5 size-3" />
                                  Deploy
                                </Button>
                              </div>
                            </div>

                            {/* Metrics Grid */}
                            <div className="mb-4 grid grid-cols-4 gap-4">
                              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                                <p className="text-xs text-white/50">Sharpe Ratio</p>
                                <p className="mt-1 text-lg font-semibold text-emerald-400">
                                  {sharpe.toFixed(2)}
                                </p>
                              </div>
                              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                                <p className="text-xs text-white/50">IC</p>
                                <p className="mt-1 text-lg font-semibold text-white/90">
                                  {ic.toFixed(3)}
                                </p>
                              </div>
                              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                                <p className="text-xs text-white/50">Annual Return</p>
                                <p className="mt-1 text-lg font-semibold text-emerald-400">
                                  {(annualReturn * 100).toFixed(1)}%
                                </p>
                              </div>
                              <div className="rounded-lg border border-white/10 bg-white/5 p-3">
                                <p className="text-xs text-white/50">Max Drawdown</p>
                                <p className="mt-1 text-lg font-semibold text-rose-400">
                                  {(maxDrawdown * 100).toFixed(1)}%
                                </p>
                              </div>
                            </div>

                            {/* Factors List */}
                            <div className="space-y-2">
                              {(run.best_factors || []).map((factor, idx) => (
                                <div
                                  key={idx}
                                  className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3"
                                >
                                  <span className="inline-flex shrink-0 rounded-full bg-amber-500/30 p-1.5">
                                    <TrendingUp className="size-3.5 text-amber-300" />
                                  </span>
                                  <span className="text-sm font-medium text-amber-200">
                                    {(factor as Record<string, unknown>).name as string}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )
                      })}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Performance Graph */}

            {/* Portfolio Snapshots */}
            <PortfolioSnapshots agentType="alpha" title="Alpha Portfolio Snapshot History" />

            {/* Trades Table */}
            <AgentTradesTable trades={alphaData?.recent_trades || []} loading={alphaLoading} mode="advanced" agentId={alphaData?.agent_id} />

            {/* Mobile Chat */}
            <div className="lg:hidden">
              <div className="mt-6">
                <AlphaChat />
              </div>
            </div>
          </div>
        </Container>
      </main>

      {/* Sidebar Chat */}
      <aside className="fixed right-0 top-16 hidden h-[calc(100vh-4rem)] w-[24rem] flex-col border-l border-white/10 bg-[#070707]/95 shadow-2xl backdrop-blur-lg lg:flex">
        <AlphaChat className="flex-1 overflow-hidden" />
      </aside>

      {/* Modals */}
      <NewHypothesisModal
        open={hypothesisModalOpen}
        onOpenChange={setHypothesisModalOpen}
        onSubmit={handleCreateRun}
      />

      <DeployAlphaModal
        open={deployModalOpen}
        onOpenChange={setDeployModalOpen}
        run={selectedRun}
        onDeploy={handleDeployAlpha}
        alphaData={alphaData}
      />

      <ResultsModal
        open={resultsModalOpen}
        onOpenChange={setResultsModalOpen}
        run={selectedRun}
        results={selectedResults}
        loading={resultsLoading}
        onDeploy={() => {
          setResultsModalOpen(false)
          setDeployModalOpen(true)
        }}
      />
    </div>
  )
}
