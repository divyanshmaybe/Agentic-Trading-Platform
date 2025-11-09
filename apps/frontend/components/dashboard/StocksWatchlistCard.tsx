import { useMemo } from "react"
import { Line } from "react-chartjs-2"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

import type { StockItem } from "@/lib/dashboardTypes"

import { createSparklineChart } from "./chartConfig"

type StocksWatchlistCardProps = {
	stocks: StockItem[]
	loading?: boolean
}

export function StocksWatchlistCard({ stocks, loading = false }: StocksWatchlistCardProps) {
	return (
		<Card className="card-glass flex flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur md:min-h-[50vh]">
			<CardHeader className="gap-2">
				<CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
					Your Holdings
				</CardDescription>
				<CardTitle className="h-title text-2xl text-[#fafafa]">Positions</CardTitle>
			</CardHeader>
			<CardContent className={stocks.length === 0 && !loading ? "flex flex-col items-center justify-center flex-1" : "flex flex-col gap-4"}>
				{loading ? (
					<>
						{[1, 2, 3, 4].map((i) => (
							<div
								key={i}
								className="h-20 animate-pulse rounded-xl border border-white/10 bg-white/7"
							/>
						))}
					</>
				) : stocks.length === 0 ? (
					<div className="text-center text-sm text-white/50">
						No positions yet. Start trading to see your holdings here.
					</div>
				) : (
					stocks.map((stock) => <StockSparklineRow key={stock.symbol} stock={stock} />)
				)}
			</CardContent>
		</Card>
	)
}

type StockSparklineRowProps = {
	stock: StockItem
}

function StockSparklineRow({ stock }: StockSparklineRowProps) {
	const { data, options, plugins } = useMemo(() => createSparklineChart(stock), [stock])
	const positive = stock.changePct >= 0

	return (
		<div className="grid grid-cols-1 items-center gap-4 rounded-xl border border-white/10 bg-white/7 px-4 py-3 text-white/70 transition hover:border-white/20 hover:bg-white/10 sm:grid-cols-[1fr_auto]">
			<div className="flex flex-col gap-1">
				<div className="flex flex-wrap items-center gap-2 text-[#fafafa]">
					<span className="text-sm font-semibold text-[#fafafa]">{stock.name}</span>
					<span className="rounded-md bg-black/60 px-2 py-0.5 text-xs uppercase tracking-wide text-white/50">
						{stock.symbol}
					</span>
					{stock.pricesError && (
						<span className="text-xs text-white/30" title="Using fallback data">⚠</span>
					)}
				</div>
				<span className={cn("text-sm font-semibold", positive ? "text-[#22c55e]" : "text-[#dc2626]")}>
					{positive ? "+" : ""}
					{stock.changePct.toFixed(2)}%
				</span>
			</div>
			<div className="h-16 min-w-[120px] sm:h-16">
				<Line data={data} options={options} plugins={plugins} />
			</div>
		</div>
	)
}
