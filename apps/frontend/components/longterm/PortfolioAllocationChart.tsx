"use client"

import { Pie } from "react-chartjs-2"
import { summaryPieChartOptions, pieDepthPlugin } from "@/components/dashboard/chartConfig"
import { ReasoningCard } from "./ReasoningCard"

interface PortfolioItem {
	ticker?: string
	percentage: number
	reasoning?: string
}

interface PortfolioAllocationChartProps {
	finalPortfolio: PortfolioItem[]
	chartData: any
}

export function PortfolioAllocationChart({ finalPortfolio, chartData }: PortfolioAllocationChartProps) {
	if (finalPortfolio.length === 0) return null

	return (
		<div className="rounded-xl border border-white/10 bg-black/25 p-6 backdrop-blur-sm">
			<h4 className="mb-4 text-lg font-semibold text-[#fafafa]">Portfolio Allocation</h4>
			<div className="flex justify-center">
				<div className="w-full max-w-md">
					<Pie
						data={chartData}
						options={summaryPieChartOptions}
						plugins={[pieDepthPlugin]}
					/>
				</div>
			</div>
			{/* Reasoning Cards */}
			<div className="mt-6 grid grid-cols-1 gap-3">
				{finalPortfolio.map((item, index) => (
					<ReasoningCard
						key={index}
						label={item.ticker || ""}
						percentage={item.percentage}
						reasoning={item.reasoning}
					/>
				))}
			</div>
		</div>
	)
}
