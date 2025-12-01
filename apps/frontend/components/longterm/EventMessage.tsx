"use client"

import { Loader2, CheckCircle2, Info, Building2, TrendingUp, FileText, Sparkles, Brain } from "lucide-react"

interface Event {
	id: string
	kind?: string
	status?: string | null
	content?: any
	[key: string]: any
}

interface EventMessageProps {
	event: Event
}

export function EventMessage({ event }: EventMessageProps) {
	const { kind, status, content } = event

	// INFO event
	if (kind === "info") {
		return (
			<div className="flex items-start gap-3 text-sm">
				<Info className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					{typeof content === "string" ? content : content.message}
				</div>
			</div>
		)
	}

	// REASONING event
	if (kind === "reasoning" && status === "thinking") {
		const message = content?.message || "Thinking..."
		return (
			<div className="flex items-start gap-3 text-sm">
				<Brain className="w-4 h-4 text-purple-400 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					{message}
				</div>
			</div>
		)
	}

	// INDUSTRY - FETCHING
	if (kind === "industry" && status === "fetching") {
		const industries = content?.industries || []
		return (
			<div className="flex items-start gap-3 text-sm">
				<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				<div className="flex-1 text-white/90">
					<span className="text-white/70">Analyzing industries:</span>{" "}
					<span className="text-cyan-300">{industries.join(", ") || "Loading..."}</span>
				</div>
			</div>
		)
	}

	// INDUSTRY - FETCHED
	if (kind === "industry" && status === "fetched") {
		const industries = content?.industries || []
		const metrics = content?.metrics || {}
		const industryCount = industries.length

		return (
			<div className="flex items-start gap-3 text-sm">
				<Building2 className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<div className="mb-1">
						<span className="text-white/70">Completed analysis of</span>{" "}
						<span className="text-amber-200 font-medium">{industryCount} industries</span>
					</div>
					{Object.keys(metrics).length > 0 && (
						<div className="mt-2 pl-4 border-l border-white/10 text-xs text-white/60">
							Metrics calculated for {Object.keys(metrics).length} industry groups
						</div>
					)}
				</div>
			</div>
		)
	}

	// INDUSTRY - DONE
	if (kind === "industry" && status === "done") {
		const industries = content?.industries || []
		const message = content?.message || "Industry analysis complete."

		return (
			<div className="flex items-start gap-3 text-sm">
				<CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<div className="mb-2">
						<span className="text-emerald-300 font-semibold">{message}</span>
					</div>
					{industries.length > 0 && (
						<div className="mt-2 pl-4 border-l border-white/10 space-y-1.5 text-xs text-white/70">
							{industries.map((industry: any, idx: number) => (
								<div key={idx}>
									<span className="text-white/50">• {industry.name}:</span>{" "}
									<span className="text-emerald-200 font-medium">{industry.percentage}%</span>
									{industry.reasoning && (
										<span className="text-white/60"> — {industry.reasoning}</span>
									)}
								</div>
							))}
						</div>
					)}
				</div>
			</div>
		)
	}

	// STOCK - FETCHING
	if (kind === "stock" && status === "fetching") {
		const ticker = content?.content || "Unknown"
		return (
			<div className="flex items-start gap-3 text-sm">
				<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				<div className="flex-1 text-white/90">
					<span className="text-white/70">Fetching data for</span>{" "}
					<span className="text-cyan-300 font-mono font-medium">{ticker}</span>
				</div>
			</div>
		)
	}

	// STOCK - FETCHED
	if (kind === "stock" && status === "fetched") {
		const ticker = content?.content || "Unknown"
		return (
			<div className="flex items-start gap-3 text-sm">
				<TrendingUp className="w-4 h-4 text-emerald-300 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<span className="text-white/70">Data retrieved for</span>{" "}
					<span className="text-emerald-200 font-mono font-medium">{ticker}</span>
				</div>
			</div>
		)
	}

	// REPORT - GENERATING
	if (kind === "report" && status === "generating") {
		const ticker = content?.ticker || "Unknown"
		return (
			<div className="flex items-start gap-3 text-sm">
				<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				<div className="flex-1 text-white/90">
					<span className="text-white/70">Generating analysis report for</span>{" "}
					<span className="text-cyan-300 font-mono font-medium">{ticker}</span>
				</div>
			</div>
		)
	}

	// REPORT - GENERATED
	if (kind === "report" && status === "generated") {
		const ticker = content?.ticker || "Unknown"
		return (
			<div className="flex items-start gap-3 text-sm">
				<FileText className="w-4 h-4 text-indigo-300 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<span className="text-white/70">Report generated for</span>{" "}
					<span className="text-indigo-200 font-mono font-medium">{ticker}</span>
				</div>
			</div>
		)
	}

	// SUMMARY event
	if (kind === "summary") {
		const summary = content?.summary || {}
		const industryList = content?.industry_list || []
		const finalPortfolio = content?.final_portfolio || []
		const tradeList = content?.trade_list || []

		return (
			<div className="flex items-start gap-3 text-sm">
				<Sparkles className="w-4 h-4 text-purple-400 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<div className="mb-2">
						<span className="text-purple-300 font-semibold">Portfolio Analysis Complete</span>
					</div>
					<div className="mt-2 space-y-1.5 pl-4 border-l border-white/10 text-xs text-white/70">
						{summary.total_stocks && (
							<div>
								<span className="text-white/50">• Stocks analyzed:</span>{" "}
								<span className="text-white/90">{summary.total_stocks}</span>
							</div>
						)}
						{summary.total_trades && (
							<div>
								<span className="text-white/50">• Trades recommended:</span>{" "}
								<span className="text-white/90">{summary.total_trades}</span>
							</div>
						)}
						{summary.total_invested && (
							<div>
								<span className="text-white/50">• Total invested:</span>{" "}
								<span className="text-green-300">₹{summary.total_invested.toLocaleString()}</span>
							</div>
						)}
						{summary.utilization_rate !== undefined && (
							<div>
								<span className="text-white/50">• Fund utilization:</span>{" "}
								<span className="text-cyan-300">{summary.utilization_rate.toFixed(1)}%</span>
							</div>
						)}
					</div>
				</div>
			</div>
		)
	}

	// Fallback for unknown event types
	return (
		<div className="flex items-start gap-3 text-sm">
			<Info className="w-4 h-4 text-white/40 mt-0.5 shrink-0" />
			<div className="flex-1 text-white/70 font-mono text-xs">
				{JSON.stringify({ kind, status, content }, null, 2)}
			</div>
		</div>
	)
}

