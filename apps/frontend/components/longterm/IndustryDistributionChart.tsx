 "use client"

import { DonutChartCard } from "./DonutChartCard"

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
		<DonutChartCard
			title="Industry Distribution"
			centerTitle="Industry Mix"
			centerSubtitle="6 Sectors"
			items={industryList.map(item => ({
				label: item.name || "",
				percentage: item.percentage
			}))}
			chartData={chartData}
		/>
	)
}
