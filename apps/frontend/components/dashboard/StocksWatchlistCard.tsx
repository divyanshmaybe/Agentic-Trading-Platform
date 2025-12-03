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
		<Card className={cn(
			"card-glass flex flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur w-full"
		)}>
			<CardHeader className="gap-2 shrink-0">
				<CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
					Your Holdings
				</CardDescription>
				<CardTitle className="h-title text-2xl text-[#fafafa]">Positions</CardTitle>
			</CardHeader>
			<CardContent className={cn(
				"flex flex-col min-h-0 flex-1",
				stocks.length === 0 && !loading ? "items-center justify-center" : "gap-4 overflow-y-auto"
			)}>
				{loading ? (
					<>
						{[1, 2, 3, 4].map((i) => (
							<div
								key={i}
								className="h-20 animate-pulse rounded-xl border border-white/10 bg-white/7 shrink-0"
							/>
						))}
					</>
				) : stocks.length === 0 ? (
					<div className="text-center text-sm text-white/50">
						No positions yet. Start trading to see your holdings here.
					</div>
				) : (
					stocks.map((stock) => (
						<div key={stock.symbol} className="shrink-0">
							<StockSparklineRow stock={stock} />
						</div>
					))
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
	const hasPriceData = stock.prices && stock.prices.length > 0 && !stock.pricesError

	return (
		<div className="grid grid-cols-1 items-center gap-4 rounded-xl border border-white/10 bg-white/7 px-4 py-3 text-white/70 transition hover:border-white/20 hover:bg-white/10 sm:grid-cols-[1fr_auto]">
			<div className="flex flex-col gap-1">
				<div className="flex flex-wrap items-center gap-2 text-[#fafafa]">
					<span className="text-sm font-semibold text-[#fafafa]">{stock.name}</span>
					<span className="rounded-md bg-black/60 px-2 py-0.5 text-xs uppercase tracking-wide text-white/50">
						{stock.symbol}
					</span>
				</div>
			</div>
			<div className="h-16 min-w-[120px] sm:h-16">
				{hasPriceData ? (
					<Line data={data} options={options} plugins={plugins} />
				) : (
					<div className="flex h-full w-full items-center justify-center rounded-lg border border-amber-500/20 bg-amber-500/5">
						<div className="flex flex-col items-center gap-1 text-center">
							<span className="text-[10px] text-amber-400/70">Price data unavailable</span>
						</div>
					</div>
				)}
			</div>
		</div>
	)
}
