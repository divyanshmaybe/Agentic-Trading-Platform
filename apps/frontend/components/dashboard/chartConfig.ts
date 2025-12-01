import type { ChartData, ChartOptions, Plugin, ScriptableContext } from "chart.js"

import type { PortfolioSummary, StockItem } from "@/lib/dashboardTypes"

type LineDatasetWithShadow = ChartData<"line">["datasets"][number] & { shadowColor: string }

const PIE_COLOR_MAP = {
  "Algorithmic Strategies": {
    fill: "#22c55e",
    border: "#14532d",
    hover: "#16a34a",
    glow: "rgba(34,197,94,0.22)",
  },
  "Long-Term Strategies": {
    fill: "#3b82f6",
    border: "#1e3a8a",
    hover: "#2563eb",
    glow: "rgba(59,130,246,0.18)",
  },
  "Intraday Strategies": {
    fill: "#f59e0b",
    border: "#92400e",
    hover: "#d97706",
    glow: "rgba(245,158,11,0.2)",
  },
  "Liquid Strategies": {
    fill: "#a855f7",
    border: "#6b21a8",
    hover: "#9333ea",
    glow: "rgba(168,85,247,0.22)",
  },
} as const satisfies Record<string, { fill: string; border: string; hover: string; glow: string }>

type PieColorKey = keyof typeof PIE_COLOR_MAP

// Mapping from API allocation types and display labels to chart color keys
const ALLOCATION_TYPE_TO_COLOR_MAP: Record<string, PieColorKey> = {
  // Display labels (what frontend shows)
  "Long-Term": "Long-Term Strategies",
  "Intraday": "Intraday Strategies",
  "Algorithmic": "Algorithmic Strategies",
  "Liquid": "Liquid Strategies",
  // API allocation types (what backend sends)
  "Low Risk": "Long-Term Strategies",
  "High Risk": "Intraday Strategies",
  "Alpha": "Algorithmic Strategies",
  // Also handle lowercase and other variations
  "low risk": "Long-Term Strategies",
  "high risk": "Intraday Strategies",
  "alpha": "Algorithmic Strategies",
  "liquid": "Liquid Strategies",
  "Low_Risk": "Long-Term Strategies",
  "High_Risk": "Intraday Strategies",
  "low_risk": "Long-Term Strategies",
  "high_risk": "Intraday Strategies",
}

const PIE_FALLBACK = {
  fill: "#4b5563",
  border: "#1f2937",
  hover: "#6b7280",
  glow: "rgba(75,85,99,0.18)",
}

const getPieColors = (label: string) => {
  // First try to map API allocation type to chart color key
  const mappedLabel = ALLOCATION_TYPE_TO_COLOR_MAP[label] || label
  return PIE_COLOR_MAP[mappedLabel as PieColorKey] ?? PIE_FALLBACK
}

export const pieDepthPlugin: Plugin<"pie"> = {
  id: "dashboard-pie-depth",
  afterDatasetsDraw(chart) {
    const meta = chart.getDatasetMeta(0)
    if (!meta?.data.length) {
      return
    }

    const dataset = chart.data.datasets[0]
    const colors = Array.isArray(dataset.backgroundColor) ? dataset.backgroundColor : []

    const { ctx } = chart
    meta.data.forEach((arc, index) => {
      const arcElement = arc as unknown as { draw: (ctx: CanvasRenderingContext2D) => void }
      const label = chart.data.labels?.[index]
      const colorConfig = getPieColors(typeof label === "string" ? label : "")
      ctx.save()
      ctx.shadowColor = colorConfig.glow
      ctx.shadowBlur = 18
      ctx.shadowOffsetX = 0
      ctx.shadowOffsetY = 2
      ctx.globalCompositeOperation = "source-over"
      if (Array.isArray(colors) && typeof colors[index] === "string") {
        ctx.fillStyle = colors[index] as string
      }
      arcElement.draw(ctx)
      ctx.restore()
    })
  },
}

export const allocationChartOptions: ChartOptions<"pie"> = {
  plugins: {
    legend: {
      position: "bottom",
      labels: {
        color: "rgba(240,240,240,0.8)",
        usePointStyle: true,
        padding: 16,
      },
    },
    tooltip: {
      backgroundColor: "rgba(18,18,18,0.95)",
      borderColor: "rgba(255,255,255,0.08)",
      borderWidth: 1,
      titleColor: "#fafafa",
      bodyColor: "rgba(224,224,224,0.85)",
    },
  },
}

// Chart options for summary pie charts - no legend, tooltips enabled
export const summaryPieChartOptions: ChartOptions<"pie"> = {
  responsive: true,                // ensure the canvas follows container size
  maintainAspectRatio: false,      // allow container height to control aspect ratio
  cutout: "62%",                   // thicker ring (adjusted)
  radius: "88%",
  layout: {
    padding: 0                     // remove any internal padding that offsets center
  },
  plugins: {
    legend: {
      display: false,
    },
    tooltip: {
      enabled: true,
      backgroundColor: "rgba(18,18,18,0.95)",
      borderColor: "rgba(255,255,255,0.08)",
      borderWidth: 1,
      titleColor: "#fafafa",
      bodyColor: "rgba(224,224,224,0.85)",
      callbacks: {
        label: function (context) {
          const label = context.label || ""
          const value = context.parsed || 0
          return `${label}: ${value.toFixed(2)}%`
        },
      },
    },
  },
}

export function createAllocationChartData(allocation: PortfolioSummary["allocation"]): ChartData<"pie"> {
  const pieFillColors = allocation.map((segment) => getPieColors(segment.label).fill)
  const pieBorderColors = allocation.map((segment) => getPieColors(segment.label).border)
  const pieHoverBorderColors = allocation.map((segment) => getPieColors(segment.label).hover)

  return {
    labels: allocation.map((segment) => segment.label),
    datasets: [
      {
        data: allocation.map((segment) => segment.value),
        backgroundColor: pieFillColors,
        hoverBackgroundColor: pieFillColors,
        borderColor: pieBorderColors,
        borderWidth: 2,
        hoverBorderColor: pieHoverBorderColors,
        borderJoinStyle: "round",
      },
    ],
  }
}

const LINE_STYLES = {
  positive: {
    border: "#22c55e",
    gradientFrom: "rgba(34,197,94,0.2)",
    gradientTo: "rgba(34,197,94,0)",
    shadow: "rgba(34,197,94,0.25)",
  },
  negative: {
    border: "#dc2626",
    gradientFrom: "rgba(220,38,38,0.12)",
    gradientTo: "rgba(220,38,38,0)",
    shadow: "rgba(220,38,38,0.15)",
  },
} as const

const createLinearGradient = (context: ScriptableContext<"line">, from: string, to: string) => {
  const { ctx, chartArea } = context.chart
  if (!chartArea) {
    return from
  }
  const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top)
  gradient.addColorStop(0, from)
  gradient.addColorStop(1, to)
  return gradient
}

export const lineDepthPlugin: Plugin<"line"> = {
  id: "dashboard-line-depth",
  afterDatasetsDraw(chart) {
    const { ctx } = chart
    chart.data.datasets.forEach((dataset, index) => {
      const meta = chart.getDatasetMeta(index)
      if (!meta || meta.hidden || !meta.dataset) {
        return
      }

      const typedDataset = dataset as typeof dataset & { shadowColor?: string }
      const shadowColor = typedDataset.shadowColor ?? "rgba(15,23,42,0.2)"

      ctx.save()
      ctx.shadowColor = shadowColor
      ctx.shadowBlur = 12
      ctx.shadowOffsetX = 0
      ctx.shadowOffsetY = 6
      ctx.globalCompositeOperation = "source-over"
      const datasetElement = meta.dataset as unknown as { draw: (ctx: CanvasRenderingContext2D) => void }
      datasetElement.draw(ctx)
      ctx.restore()
    })
  },
}

export function createSparklineChart(stock: StockItem): {
  data: ChartData<"line">
  options: ChartOptions<"line">
  plugins: Plugin<"line">[]
} {
  // Determine color based on first vs last price in the sparkline
  const firstPrice = stock.prices[0] || 0
  const lastPrice = stock.prices[stock.prices.length - 1] || 0
  const positive = lastPrice >= firstPrice
  const hasError = stock.pricesError === true
  const palette = positive ? LINE_STYLES.positive : LINE_STYLES.negative

  const dataset: LineDatasetWithShadow = {
    label: stock.symbol,
    data: stock.prices,
    borderColor: hasError ? "rgba(156, 163, 175, 0.5)" : palette.border,
    backgroundColor: (context: ScriptableContext<"line">) => {
      if (hasError) {
        return createLinearGradient(context, "rgba(156, 163, 175, 0.05)", "rgba(156, 163, 175, 0)")
      }
      return createLinearGradient(context, palette.gradientFrom, palette.gradientTo)
    },
    fill: true,
    tension: 0,
    borderWidth: hasError ? 1 : 2,
    pointRadius: 0,
    shadowColor: hasError ? "rgba(156, 163, 175, 0.1)" : palette.shadow,
    borderCapStyle: "round",
    borderJoinStyle: "round",
    borderDash: hasError ? [3, 3] : undefined,
  }

  const data: ChartData<"line"> = {
    labels: stock.prices.map((_, idx) => `t${idx + 1}`),
    datasets: [dataset],
  }

  const options: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { enabled: false },
    },
    scales: {
      x: { display: false },
      y: { display: false },
    },
  }

  return { data, options, plugins: [lineDepthPlugin] }
}

// Color palette for dynamic pie charts - generates distinct colors
const DYNAMIC_COLORS = [
  { fill: "#3b82f6", border: "#1e3a8a", hover: "#2563eb", glow: "rgba(59,130,246,0.18)" }, // Blue
  { fill: "#22c55e", border: "#14532d", hover: "#16a34a", glow: "rgba(34,197,94,0.22)" }, // Green
  { fill: "#f59e0b", border: "#92400e", hover: "#d97706", glow: "rgba(245,158,11,0.2)" }, // Amber
  { fill: "#a855f7", border: "#6b21a8", hover: "#9333ea", glow: "rgba(168,85,247,0.22)" }, // Purple
  { fill: "#ef4444", border: "#991b1b", hover: "#dc2626", glow: "rgba(239,68,68,0.2)" }, // Red
  { fill: "#06b6d4", border: "#164e63", hover: "#0891b2", glow: "rgba(6,182,212,0.18)" }, // Cyan
  { fill: "#f97316", border: "#9a3412", hover: "#ea580c", glow: "rgba(249,115,22,0.2)" }, // Orange
  { fill: "#8b5cf6", border: "#5b21b6", hover: "#7c3aed", glow: "rgba(139,92,246,0.22)" }, // Violet
  { fill: "#10b981", border: "#065f46", hover: "#059669", glow: "rgba(16,185,129,0.18)" }, // Emerald
  { fill: "#ec4899", border: "#9f1239", hover: "#db2777", glow: "rgba(236,72,153,0.2)" }, // Pink
  { fill: "#14b8a6", border: "#134e4a", hover: "#0d9488", glow: "rgba(20,184,166,0.18)" }, // Teal
  { fill: "#6366f1", border: "#312e81", hover: "#4f46e5", glow: "rgba(99,102,241,0.18)" }, // Indigo
  { fill: "#84cc16", border: "#365314", hover: "#65a30d", glow: "rgba(132,204,22,0.18)" }, // Lime
  { fill: "#f43f5e", border: "#9f1239", hover: "#e11d48", glow: "rgba(244,63,94,0.2)" }, // Rose
  { fill: "#0ea5e9", border: "#0c4a6e", hover: "#0284c7", glow: "rgba(14,165,233,0.18)" }, // Sky
  { fill: "#64748b", border: "#1e293b", hover: "#475569", glow: "rgba(100,116,139,0.18)" }, // Slate
]

/**
 * Generate a color palette for dynamic pie charts
 * Cycles through predefined colors if more segments than available colors
 */
function generateColorPalette(count: number): Array<{ fill: string; border: string; hover: string; glow: string }> {
  const colors: Array<{ fill: string; border: string; hover: string; glow: string }> = []
  for (let i = 0; i < count; i++) {
    colors.push(DYNAMIC_COLORS[i % DYNAMIC_COLORS.length])
  }
  return colors
}

/**
 * Type for dynamic pie chart data items
 * Supports both industry_list (name) and final_portfolio (ticker) formats
 */
type DynamicPieItem = {
  name?: string
  ticker?: string
  percentage: number
  [key: string]: any // Allow additional fields
}

/**
 * Create pie chart data from dynamic arrays (industry_list or final_portfolio)
 */
export function createDynamicPieChartData(
  items: DynamicPieItem[]
): ChartData<"pie"> {
  if (!items || items.length === 0) {
    return {
      labels: [],
      datasets: [
        {
          data: [],
          backgroundColor: [],
          borderColor: [],
          hoverBorderColor: [],
        },
      ],
    }
  }

  const colors = generateColorPalette(items.length)
  const labels = items.map((item) => item.name || item.ticker || "Unknown")
  const percentages = items.map((item) => item.percentage || 0)

  return {
    labels,
    datasets: [
      {
        data: percentages,
        backgroundColor: colors.map((c) => c.fill),
        hoverBackgroundColor: colors.map((c) => c.fill),
        borderColor: colors.map((c) => c.border),
        borderWidth: 2,
        hoverBorderColor: colors.map((c) => c.hover),
        borderJoinStyle: "round",
      },
    ],
  }
}

