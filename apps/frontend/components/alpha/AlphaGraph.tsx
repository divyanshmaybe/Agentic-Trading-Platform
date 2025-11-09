"use client"

import { useMemo } from "react"
import { Line } from "react-chartjs-2"
import { motion } from "framer-motion"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Chart } from "@/lib/chart"
import { alphaSeries } from "@/mock/alphaData"

const animation = {
	hidden: { opacity: 0, y: 20 },
	show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } },
}

export function AlphaGraph() {
	useMemo(() => Chart, [])

	const chartData = useMemo(
		() => ({
			labels: alphaSeries.map((point) => point.time),
			datasets: [
				{
					label: "Bullish",
					data: alphaSeries.map((point) => point.bullish),
					borderColor: "#22c55e",
					backgroundColor: "rgba(34, 197, 94, 0.15)",
					fill: true,
					tension: 0.4,
					pointRadius: 0,
				},
				{
					label: "Bearish",
					data: alphaSeries.map((point) => point.bearish),
					borderColor: "#ef4444",
					backgroundColor: "rgba(239, 68, 68, 0.15)",
					fill: true,
					tension: 0.4,
					pointRadius: 0,
				},
			],
		}),
		[],
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
		<Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-black/40 shadow-xl">
			<CardHeader>
				<CardTitle className="h-title text-xl text-white">Performance Today</CardTitle>
			</CardHeader>
			<CardContent>
				<motion.div
					className="relative h-[320px] w-full rounded-2xl border border-white/10 bg-black/30 p-4"
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
