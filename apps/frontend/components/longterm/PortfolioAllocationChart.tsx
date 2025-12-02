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
		<div className="flex h-screen flex-col rounded-2xl border border-white/10 bg-white/6 p-6 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
			<DonutChartCard
				title="Portfolio Allocation"
				centerTitle="Portfolio Mix"
				centerSubtitle={`${finalPortfolio.length} stocks`}
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
							className="group flex items-start justify-between rounded-xl border border-white/10 bg-white/8 px-4 py-3 text-sm hover:bg-white/10 transition-colors backdrop-blur-sm"
						>
							<div className="flex items-start gap-3 flex-1 min-w-0">
								<span
									className="inline-flex h-4 w-4 rounded-full mt-1 shrink-0"
									style={{ backgroundColor: color }}
								/>
								<div className="flex flex-col flex-1 min-w-0">
									<span className="text-xl font-medium text-[#fafafa]">
										{item.ticker || ""}
									</span>
									{item.reasoning && (
										<span className="text-lg text-white/60 opacity-0 max-h-0 group-hover:opacity-100 group-hover:max-h-none transition-all duration-300 delay-150 ease-in-out overflow-hidden whitespace-normal wrap-break-word">
											{item.reasoning}
										</span>
									)}
								</div>
							</div>
							<div className="text-right text-xl font-semibold text-emerald-400 shrink-0 ml-4">
								{item.percentage.toFixed(2)}%
							</div>
						</div>
					)
				})}
			</div>
		</div>
	)
}
