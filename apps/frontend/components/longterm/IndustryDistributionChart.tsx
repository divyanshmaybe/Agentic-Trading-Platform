"use client"

import { Pie } from "react-chartjs-2"
import { summaryPieChartOptions, pieDepthPlugin } from "@/components/dashboard/chartConfig"
import { ReasoningCard } from "./ReasoningCard"

interface IndustryItem {
	name?: string
	percentage: number
	reasoning?: string
}

interface IndustryDistributionChartProps {
	industryList: IndustryItem[]
	chartData: any
}

export function IndustryDistributionChart({ industryList, chartData }: IndustryDistributionChartProps) {
	if (industryList.length === 0) return null

	return (
		<div className="rounded-xl border border-white/10 bg-black/25 p-6 backdrop-blur-sm">
			<h4 className="mb-4 text-lg font-semibold text-[#fafafa]">Industry Distribution</h4>
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
				{industryList.map((item, index) => (
					<ReasoningCard
						key={index}
						label={item.name || ""}
						percentage={item.percentage}
						reasoning={item.reasoning}
					/>
				))}
			</div>
		</div>
	)
}
