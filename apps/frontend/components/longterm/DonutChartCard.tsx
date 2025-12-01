"use client"

import { Pie } from "react-chartjs-2"
import { summaryPieChartOptions, pieDepthPlugin } from "@/components/dashboard/chartConfig"

interface DonutItem {
	label: string
	percentage: number
}

interface DonutChartCardProps {
	title: string
	centerTitle: string
	centerSubtitle: string
	items: DonutItem[]
	chartData: any
}

export function DonutChartCard({
	title,
	centerTitle,
	centerSubtitle,
	items,
	chartData
}: DonutChartCardProps) {
	if (!items.length) return null

	const backgroundColors =
		(Array.isArray(chartData?.datasets?.[0]?.backgroundColor) &&
			chartData.datasets[0].backgroundColor) ||
		[]

	return (
		<div className="rounded-2xl border border-white/10 bg-[#111] p-6 shadow-lg shadow-black/20 animate-[fadeIn_0.4s_ease-out]">
			<h4 className="mb-6 text-sm font-medium tracking-[0.2em] text-white/50 uppercase">
				{title}
			</h4>
			<div className="flex items-center justify-center">
				<div className="relative w-full max-w-sm h-[300px] sm:h-[340px]">
					<Pie
						data={chartData}
						options={summaryPieChartOptions}
						plugins={[pieDepthPlugin]}
					/>
					<div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center transform -translate-y-[2px]">
						<div className="text-xs font-medium text-white/50 uppercase tracking-[0.2em]">
							{centerTitle}
						</div>
						<div className="mt-1 text-2xl font-semibold text-white">{centerSubtitle}</div>
					</div>
				</div>
			</div>

			<div className="mt-6 space-y-2">
				{items.map((item, index) => {
					const color = backgroundColors[index] as string | undefined
					return (
						<div
							key={`${item.label}-${index}`}
							className="flex items-center justify-between rounded-xl border border-white/5 bg-[#141414] px-3 py-2 text-sm hover:bg-[#1c1c1c] transition-colors"
						>
							<div className="flex items-center gap-3">
								<span
									className="inline-flex h-3 w-3 rounded-full"
									style={{ backgroundColor: color }}
								/>
								<span className="text-[13px] font-medium text-white">
									{item.label}
								</span>
							</div>
							<div className="text-right text-sm font-semibold text-emerald-400">
								{item.percentage.toFixed(2)}%
							</div>
						</div>
					)
				})}
			</div>
		</div>
	)
}


