import { useMemo } from "react"
import { Line } from "react-chartjs-2"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

import type { StockItem } from "@/lib/dashboardTypes"

import { createSparklineChart } from "./chartConfig"

type StocksWatchlistCardProps = {
	stocks: StockItem[]
}

export function StocksWatchlistCard({ stocks }: StocksWatchlistCardProps) {
	return (
		<Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
			<CardHeader className="gap-2">
				<CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
					Stocks
				</CardDescription>
				<CardTitle className="h-title text-2xl text-[#fafafa]">Watchlist</CardTitle>
			</CardHeader>
			<CardContent className="flex flex-col gap-4">
				{stocks.map((stock) => (
					<StockSparklineRow key={stock.symbol} stock={stock} />
				))}
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
		<div className="neon-hover grid grid-cols-[1.2fr_auto] items-center gap-4 rounded-xl border border-white/10 bg-white/7 px-4 py-3 text-white/70 transition hover:border-white/20 hover:bg-white/10">
			<div className="flex flex-col">
				<div className="flex items-center gap-2 text-[#fafafa]">
					<span className="text-sm font-semibold text-[#fafafa]">{stock.name}</span>
					<span className="rounded-md bg-black/60 px-2 py-0.5 text-xs uppercase tracking-wide text-white/50">
						{stock.symbol}
					</span>
				</div>
				<span className={cn("text-sm font-semibold", positive ? "text-[#22c55e]" : "text-[#ef4444]")}>
					{positive ? "+" : ""}
					{stock.changePct.toFixed(2)}%
				</span>
			</div>
			<div className="h-16">
				<Line data={data} options={options} plugins={plugins} />
			</div>
		</div>
	)
}
