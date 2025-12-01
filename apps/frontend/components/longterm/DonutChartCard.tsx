"use client"

import { Pie } from "react-chartjs-2"
import { summaryPieChartOptions, pieDepthPlugin } from "@/components/dashboard/chartConfig"

interface DonutChartCardProps {
	title: string
	centerTitle: string
	centerSubtitle: string
	chartData: any
}

export function DonutChartCard({
	title,
	centerTitle,
	centerSubtitle,
	chartData
}: DonutChartCardProps) {
	return (
		<div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
			<h4 className="text-sm font-medium tracking-[0.2em] text-white/60 uppercase">
				{title}
			</h4>
			<div className="flex items-center justify-center">
				<div className="relative w-full max-w-sm h-[300px] sm:h-[340px]">
					<Pie data={chartData} options={summaryPieChartOptions} plugins={[pieDepthPlugin]} />
					<div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center transform -translate-y-[2px]">
						<div className="text-xs font-medium text-white/60 uppercase tracking-[0.2em]">
							{centerTitle}
						</div>
						<div className="mt-1 text-2xl font-semibold text-[#fafafa]">{centerSubtitle}</div>
					</div>
				</div>
			</div>
		</div>
	)
}


