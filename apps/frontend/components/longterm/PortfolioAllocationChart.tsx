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
		<div className="flex h-screen flex-col rounded-2xl border border-white/10 bg-[#111] p-6 shadow-lg shadow-black/20">
			<DonutChartCard
				title="Portfolio Allocation"
				centerTitle="Portfolio Mix"
				centerSubtitle="16 Stocks"
				chartData={chartData}
			/>

			<div className="mt-6 flex-1 space-y-2 overflow-y-auto pr-2">
				{finalPortfolio.map((item, index) => {
					const color = Array.isArray(chartData?.datasets?.[0]?.backgroundColor)
						? (chartData.datasets[0].backgroundColor[index] as string | undefined)
						: undefined

					return (
						<div
							key={`${item.ticker || "stock"}-${index}`}
							className="flex items-center justify-between rounded-xl border border-white/5 bg-[#141414] px-3 py-2 text-sm hover:bg-[#1c1c1c] transition-colors"
							title={item.reasoning}
						>
							<div className="flex items-center gap-3">
								<span
									className="inline-flex h-3 w-3 rounded-full"
									style={{ backgroundColor: color }}
								/>
								<div className="flex flex-col">
									<span className="text-[13px] font-medium text-white">
										{item.ticker || ""}
									</span>
									{item.reasoning && (
										<span className="text-[11px] text-gray-400 line-clamp-1">
											{item.reasoning}
										</span>
									)}
								</div>
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
