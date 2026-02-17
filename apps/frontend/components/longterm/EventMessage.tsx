"use client"

import { useState } from "react"
import { Loader2, CheckCircle2, Info, Building2, TrendingUp, FileText, Brain } from "lucide-react"
import type { EffectiveStatus } from "./useEventResolution"
import { Button } from "@/components/ui/button"
import { CompanyReportModal } from "./CompanyReportModal"

interface Event {
	id: string
	kind?: string
	status?: string | null
	content?: any
	[key: string]: any
}

interface EventMessageProps {
	event: Event
	resolvedStatus?: EffectiveStatus
}

export function EventMessage({ event, resolvedStatus }: EventMessageProps) {
	const { kind, status, content } = event
	const [reportModalOpen, setReportModalOpen] = useState(false)

	const isCompleted = resolvedStatus === "completed"
	const isInProgress = resolvedStatus === "in_progress"
	const isError = resolvedStatus === "error"
	const wasFetching = status === "fetching" || status === "generating"
	const isDimmed = isCompleted && wasFetching

	// INFO event
	if (kind === "info") {
		return (
			<div className="flex items-start gap-3 text-lg mr-4">
				<Info className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					{typeof content === "string" ? content : content.message}
				</div>
			</div>
		)
	}

	// REASONING event
	if (kind === "reasoning" && status === "thinking") {
		const message = (content?.message || "Thinking...") as string
		const parts = message.split("**")
		return (
			<div className="flex items-start gap-3 text-lg mr-4">
				<Brain className="w-4 h-4 text-purple-400 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					{parts.map((part, index) =>
						index % 2 === 1 ? <strong key={index} className="font-bold text-white">{part}</strong> : part
					)}
				</div>
			</div>
		)
	}

	// STAGE event
	if (kind === "stage") {
		const message = content?.message || "Processing..."
		const stage = content?.stage || "unknown"
		const isProgress = status === "progress"
		const isStart = status === "start"
		const localCompleted = status === "completed" || status === "done"
		const localError = status === "error"
		const finalCompleted = resolvedStatus === "completed" || localCompleted
		const finalError = resolvedStatus === "error" || localError
		const finalInProgress = resolvedStatus === "in_progress" || (isProgress || isStart)

		return (
			<div className={`flex items-start gap-3 text-lg mr-4 ${isDimmed ? "opacity-60" : ""}`}>
				{finalInProgress && !finalCompleted ? (
					<Loader2 className="w-4 h-4 text-blue-400 mt-0.5 shrink-0 animate-spin" />
				) : finalCompleted ? (
					<CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
				) : finalError ? (
					<Info className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
				) : (
					<Info className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
				)}
				<div className={`flex-1 ${isDimmed ? "text-white/60" : "text-white/90"}`}>
					<div className="mb-1">
						<span className={
							finalError
								? "text-red-300 font-bold"
								: finalCompleted
									? "text-emerald-300 font-bold"
									: finalInProgress
										? "text-blue-300 font-bold"
										: "text-cyan-300 font-bold"
						}>{message}</span>
					</div>
					{stage && (
						<div className="text-sm text-white/60">
							<span className="text-white/50">Stage:</span>{" "}
							<span className="text-blue-300">{stage}</span>
						</div>
					)}
				</div>
			</div>
		)
	}

	// INDUSTRY - FETCHING
	if (kind === "industry" && status === "fetching") {
		const industries = content?.industries || []
		const showSpinner = isInProgress && !isCompleted
		return (
			<div className={`flex items-start gap-3 text-lg mr-4 ${isDimmed ? "opacity-60" : ""}`}>
				{showSpinner ? (
					<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				) : isCompleted ? (
					<CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
				) : (
					<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				)}
				<div className={`flex-1 ${isDimmed ? "text-white/60" : "text-white/90"}`}>
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
			<div className="flex items-start gap-3 text-lg mr-4">
				<Building2 className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<div className="mb-1">
						<span className="text-white/70">Completed analysis of</span>{" "}
						<span className="text-amber-200 font-medium">{industryCount} industries</span>
					</div>
					{Object.keys(metrics).length > 0 && (
						<div className="mt-2 pl-4 border-l border-white/10 text-sm text-white/60">
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
			<div className="flex items-start gap-3 text-lg mr-4">
				<CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<div className="mb-2">
						<span className="text-emerald-300 font-semibold">{message}</span>
					</div>
					{industries.length > 0 && (
						<div className="mt-2 pl-4 border-l border-white/10 space-y-1.5 text-sm text-white/70">
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
		const showSpinner = isInProgress && !isCompleted
		return (
			<div className={`flex items-start gap-3 text-lg mr-4 ${isDimmed ? "opacity-60" : ""}`}>
				{showSpinner ? (
					<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				) : isCompleted ? (
					<CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
				) : (
					<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				)}
				<div className={`flex-1 ${isDimmed ? "text-white/60" : "text-white/90"}`}>
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
			<div className="flex items-start gap-3 text-lg mr-4">
				<TrendingUp className="w-4 h-4 text-emerald-300 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<span className="text-white/70">Data retrieved for</span>{" "}
					<span className="text-emerald-200 font-mono font-medium">{ticker}</span>
				</div>
			</div>
		)
	}

	// REPORT - CACHED
	if (kind === "report" && status === "cached") {
		const ticker = content?.ticker || "Unknown"
		return (
			<div className="flex items-start gap-3 text-lg mr-4">
				<FileText className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
				<div className="flex-1 text-white/90">
					<span className="text-white/70">Using cached report for</span>{" "}
					<span className="text-amber-200 font-mono font-medium">{ticker}</span>
				</div>
			</div>
		)
	}

	// REPORT - GENERATING
	if (kind === "report" && status === "generating") {
		const ticker = content?.ticker || "Unknown"
		const showSpinner = isInProgress && !isCompleted
		return (
			<div className={`flex items-start gap-3 text-lg mr-4 ${isDimmed ? "opacity-60" : ""}`}>
				{showSpinner ? (
					<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				) : isCompleted ? (
					<CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
				) : (
					<Loader2 className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0 animate-spin" />
				)}
				<div className={`flex-1 ${isDimmed ? "text-white/60" : "text-white/90"}`}>
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
			<>
				<div className="flex items-start gap-3 text-lg mr-4">
					<FileText className="w-4 h-4 text-indigo-300 mt-0.5 shrink-0" />
					<div className="flex flex-col flex-1 text-white/90">
						<div className="flex items-center gap-3 flex-wrap">
							<span className="text-white/70">Report generated for</span>
							<span className="text-indigo-200 font-mono font-medium">{ticker}</span>
						</div>
						<Button
							variant="ghost"
							size="sm"
							onClick={() => setReportModalOpen(true)}
							className="mt-2 h-auto px-2 py-1 text-xs text-indigo-300 hover:text-indigo-200 hover:bg-indigo-500/10 self-start"
						>
							View Report
						</Button>
					</div>
				</div>
				<CompanyReportModal
					open={reportModalOpen}
					onOpenChange={setReportModalOpen}
					ticker={ticker}
				/>
			</>
		)
	}

	// SUMMARY event
	if (kind === "summary") {
		const summary = content?.summary || {}
		const industryList = content?.industry_list || []
		const finalPortfolio = content?.final_portfolio || []
		const tradeList = content?.trade_list || []
		const summaryCompleted = resolvedStatus === "completed" || resolvedStatus === undefined

		return (
			<div className="flex items-start gap-3 text-lg mr-4">
				{summaryCompleted ? (
					<CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
				) : (
					<Loader2 className="w-4 h-4 text-purple-400 mt-0.5 shrink-0 animate-spin" />
				)}
				<div className="flex-1 text-white/90">
					<div className="mb-2">
						<span className="text-purple-300 font-semibold">Portfolio Analysis Complete</span>
					</div>
					<div className="mt-2 space-y-1.5 pl-4 border-l border-white/10 text-sm text-white/70">
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
		<div className="flex items-start gap-3 text-lg mr-4">
			<Info className="w-4 h-4 text-white/40 mt-0.5 shrink-0" />
			<div className="flex-1 text-white/70 font-mono text-sm">
				{JSON.stringify({ kind, status, content }, null, 2)}
			</div>
		</div>
	)
}

