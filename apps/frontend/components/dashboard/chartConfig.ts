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
      ctx.shadowBlur = 14
      ctx.shadowOffsetX = 0
      ctx.shadowOffsetY = 4
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

