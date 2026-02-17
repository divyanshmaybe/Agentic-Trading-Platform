"use client"

import { useEffect, useState, useMemo } from "react"
import { Line } from "react-chartjs-2"
import type { ChartData, ScriptableContext } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Loader2 } from "lucide-react"
import "@/lib/chart"

const PORTFOLIO_API_URL = process.env.NEXT_PUBLIC_PORTFOLIO_API_URL || "http://localhost:8000"

type PortfolioSnapshotItem = {
  snapshot_at: string
  current_value: string
  realized_pnl: string
  unrealized_pnl: string
}

type PortfolioSnapshotsResponse = {
  items: PortfolioSnapshotItem[]
  total: number
}

type PortfolioSnapshotsProps = {
  agentType?: "alpha" | "low_risk" | "high_risk" | null
  limit?: number
  title?: string
  className?: string
}

function getAccessToken(): string | null {
  if (typeof window !== "undefined") {
    const cookies = document.cookie.split("; ")
    const entry = cookies.find((c) => c.trim().startsWith("access_token="))
    if (entry) {
      const [, value] = entry.split("=")
      return value ? decodeURIComponent(value) : null
    }
    return localStorage.getItem("access_token")
  }
  return null
}

const gradientFill = (from: string, to: string) =>
  (context: ScriptableContext<"line">) => {
    const { ctx, chartArea } = context.chart
    if (!chartArea) {
      return from
    }

    const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top)
    gradient.addColorStop(0, from)
    gradient.addColorStop(1, to)
    return gradient
  }

export function PortfolioSnapshots({
  agentType = null,
  limit = 100,
  title = "Portfolio Snapshot History",
  className = "",
}: PortfolioSnapshotsProps) {
  const [data, setData] = useState<PortfolioSnapshotItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Only run in browser
    if (typeof window === "undefined") return

    let isMounted = true

    async function fetchSnapshots() {
      try {
        if (!isMounted) return

        setLoading(true)
        setError(null)

        const token = getAccessToken()
        if (!token) {
          if (isMounted) {
            setError("Authentication required")
            setLoading(false)
          }
          return
        }

        // Build the API endpoint
        let endpoint = `${PORTFOLIO_API_URL}/api/portfolio/snapshots`
        if (agentType) {
          endpoint = `${PORTFOLIO_API_URL}/api/portfolio/agents/${agentType}/snapshots`
        }

        const params = new URLSearchParams({ limit: limit.toString() })
        const url = `${endpoint}?${params.toString()}`

        // Validate URL
        if (!PORTFOLIO_API_URL || PORTFOLIO_API_URL === "undefined") {
          if (isMounted) {
            setError("Portfolio server URL is not configured. Please set NEXT_PUBLIC_PORTFOLIO_API_URL environment variable.")
            setLoading(false)
          }
          return
        }

        let response: Response
        try {
          response = await fetch(url, {
            method: "GET",
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
          })
        } catch (networkError) {
          // Handle network errors (CORS, connection refused, etc.)
          if (isMounted) {
            console.error("Network error fetching portfolio snapshots:", networkError)
            setError(
              networkError instanceof TypeError && networkError.message.includes("fetch")
                ? "Unable to connect to portfolio server. Please check if the server is running."
                : `Network error: ${networkError instanceof Error ? networkError.message : "Unknown error"}`
            )
            setLoading(false)
          }
          return
        }

        if (!isMounted) return

        if (!response.ok) {
          // Handle 404 for agent not found - this is expected if user doesn't have this agent type
          if (response.status === 404 && agentType) {
            if (isMounted) {
              setData([])
              setLoading(false)
            }
            return
          }
          
          // Try to get error message from response
          let errorMessage = `Failed to fetch snapshots: ${response.statusText}`
          try {
            const errorData = await response.json()
            errorMessage = errorData.detail || errorData.message || errorMessage
          } catch {
            // If response is not JSON, use status text
          }
          throw new Error(errorMessage)
        }

        const result: PortfolioSnapshotsResponse = await response.json()
        if (isMounted) {
          setData(result.items || [])
        }
      } catch (err) {
        if (isMounted) {
          console.error("Error fetching portfolio snapshots:", err)
          setError(err instanceof Error ? err.message : "Failed to load snapshots")
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }

    fetchSnapshots()

    // Poll every 30 seconds for updates
    const pollInterval = setInterval(() => {
      if (isMounted) {
        fetchSnapshots()
      }
    }, 30000)

    return () => {
      isMounted = false
      clearInterval(pollInterval)
    }
  }, [agentType, limit])

  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    // Sort by snapshot_at
    const sortedData = [...data].sort(
      (a, b) => new Date(a.snapshot_at).getTime() - new Date(b.snapshot_at).getTime()
    )

    const labels = sortedData.map((d) => {
      const date = new Date(d.snapshot_at)
      return date.toLocaleDateString("en-IN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    })

    // Parse the decimal strings to numbers
    // The API returns very long decimal strings, we need to parse them correctly
    const parseDecimalString = (str: string): number => {
      if (!str || str === "0") return 0
      // Remove leading zeros but preserve the sign and decimal point
      let cleaned = str.trim()
      // Handle negative values (they start with -)
      const isNegative = cleaned.startsWith("-")
      if (isNegative) {
        cleaned = cleaned.substring(1)
      }
      // Remove leading zeros
      cleaned = cleaned.replace(/^0+/, "") || "0"
      // If it's all zeros, return 0
      if (cleaned === "0" || cleaned === ".") return 0
      // Parse the number
      const parsed = parseFloat(cleaned) || 0
      return isNegative ? -parsed : parsed
    }

    const currentValues = sortedData.map((d) => parseDecimalString(d.current_value))
    const realizedPnls = sortedData.map((d) => parseDecimalString(d.realized_pnl))
    const unrealizedPnls = sortedData.map((d) => parseDecimalString(d.unrealized_pnl))

    const chartData: ChartData<"line"> = {
      labels,
      datasets: [
        {
          label: "Current Value",
          data: currentValues,
          borderColor: "#3b82f6",
          backgroundColor: gradientFill("rgba(59,130,246,0.2)", "rgba(59,130,246,0)"),
          borderWidth: 2,
          tension: 0,
          fill: true,
          pointRadius: 0,
          borderCapStyle: "butt",
          borderJoinStyle: "miter",
        },
        {
          label: "Realized P&L",
          data: realizedPnls,
          borderColor: "#22c55e",
          backgroundColor: "rgba(34,197,94,0.1)",
          borderWidth: 1.5,
          tension: 0,
          fill: false,
          pointRadius: 2,
          pointHoverRadius: 4,
          borderCapStyle: "butt",
          borderJoinStyle: "miter",
        },
        {
          label: "Unrealized P&L",
          data: unrealizedPnls,
          borderColor: "#fbbf24",
          backgroundColor: "rgba(251,191,36,0.1)",
          borderWidth: 1.5,
          tension: 0,
          fill: false,
          pointRadius: 2,
          pointHoverRadius: 4,
          borderCapStyle: "butt",
          borderJoinStyle: "miter",
        },
      ],
    }

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: "easeOutQuart" as const },
      plugins: {
        legend: {
          labels: {
            color: "#E5E5E5",
          },
        },
        tooltip: {
          mode: "index" as const,
          intersect: false,
          backgroundColor: "rgba(22,26,30,0.95)",
          borderColor: "#1f2937",
          borderWidth: 1,
          titleColor: "#E5E5E5",
          bodyColor: "#9CA3AF",
          callbacks: {
            label: (context: any) => {
              const value = context.parsed.y
              return `${context.dataset.label}: ₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            },
          },
        },
      },
      interaction: { mode: "nearest" as const, intersect: false },
      scales: {
        x: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: { color: "#9CA3AF" },
        },
        y: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "#9CA3AF",
            callback: (value: any) => `₹${(value as number).toLocaleString("en-IN")}`,
          },
        },
      },
    }

    return { data: chartData, options }
  }, [data])

  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`}>
        <CardHeader>
          <CardTitle className="h-title text-xl text-[#fafafa]">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-[360px] items-center justify-center">
            <Loader2 className="size-6 animate-spin text-white/60" />
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`}>
        <CardHeader>
          <CardTitle className="h-title text-xl text-[#fafafa]">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-[360px] items-center justify-center text-white/60">{error}</div>
        </CardContent>
      </Card>
    )
  }

  if (!chart || !data || data.length === 0) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`}>
        <CardHeader>
          <CardTitle className="h-title text-xl text-[#fafafa]">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-[360px] items-center justify-center text-white/60">No snapshot data available</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`}>
      <CardHeader>
        <CardTitle className="h-title text-xl text-[#fafafa]">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[360px] w-full rounded-xl border border-white/10 bg-black/20 p-2">
          <Line data={chart.data} options={chart.options} />
        </div>
      </CardContent>
    </Card>
  )
}

