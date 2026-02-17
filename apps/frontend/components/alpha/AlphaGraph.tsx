"use client"

import { useMemo } from "react"
import { Line } from "react-chartjs-2"
import { motion, type Variants } from "framer-motion"
import type { ScriptableLineSegmentContext } from "chart.js"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Chart } from "@/lib/chart"
import { alphaSeries } from "@/mock/alphaData"

const GREEN = "#22c55e"
const GREEN_FILL = "rgba(34, 197, 94, 0.18)"
const RED = "#ef4444"
const RED_FILL = "rgba(239, 68, 68, 0.15)"

const animation: Variants = {
	hidden: { opacity: 0, y: 20 },
	show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.37, 0, 0.63, 1] } },
}

const resolveSegmentColor = (ctx: ScriptableLineSegmentContext) => {
	const { p0, p1 } = ctx
	if (!p0 || !p1) return GREEN

	const y0 = p0.parsed.y as number
	const y1 = p1.parsed.y as number

	if (y1 > y0) return GREEN
	if (y1 < y0) return RED
	return y1 >= 0 ? GREEN : RED
}

export function AlphaGraph() {
	useMemo(() => Chart, [])

	const performanceValues = useMemo(
		() => alphaSeries.map((point) => Number((point.bullish + point.bearish).toFixed(2))),
		[],
	)

	const chartData = useMemo(
		() => ({
			labels: alphaSeries.map((point) => point.time),
			datasets: [
				{
					label: "Net Performance",
					data: performanceValues,
					fill: {
						target: "origin",
						above: GREEN_FILL,
						below: RED_FILL,
					},
					borderColor: GREEN,
					segment: {
						borderColor: (ctx: ScriptableLineSegmentContext) => resolveSegmentColor(ctx),
					} as any,
					pointRadius: 0,
					tension: 0.35,
				},
			],
		}),
		[performanceValues],
	)

	const chartOptions = useMemo(
		() => ({
			responsive: true,
			maintainAspectRatio: false,
			plugins: {
				legend: {
					labels: { color: "#e5e7eb", usePointStyle: true, boxWidth: 8 },
				},
				tooltip: {
					callbacks: {
						label: (context: any) => `${context.dataset.label}: ${context.parsed.y.toFixed(2)}%`,
					},
				},
			},
			scales: {
				x: {
					ticks: { color: "#9ca3af" },
					grid: { color: "rgba(148, 163, 184, 0.15)" },
				},
				y: {
					ticks: {
						color: "#9ca3af",
						callback: (value: string | number) => `${value}%`,
					},
					grid: { color: "rgba(148, 163, 184, 0.1)" },
				},
			},
		}),
		[],
	)

	return (
		<Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
			<CardHeader>
				<CardTitle className="h-title text-xl text-[#fafafa]">Performance Today</CardTitle>
			</CardHeader>
			<CardContent>
				<motion.div
					className="relative h-[320px] w-full rounded-2xl border border-white/10 bg-black/25 p-4"
					variants={animation}
					initial="hidden"
					animate="show"
				>
					<Line data={chartData} options={chartOptions} />
				</motion.div>
			</CardContent>
		</Card>
	)
}
