 "use client"

import { DonutChartCard } from "./DonutChartCard"

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
		<DonutChartCard
			title="Portfolio Allocation"
			centerTitle="Portfolio Mix"
			centerSubtitle="16 Stocks"
			items={finalPortfolio.map(item => ({
				label: item.ticker || "",
				percentage: item.percentage
			}))}
			chartData={chartData}
		/>
	)
}
