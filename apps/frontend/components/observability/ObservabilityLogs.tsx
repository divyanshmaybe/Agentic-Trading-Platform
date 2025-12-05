import { format } from "date-fns"
import { motion } from "framer-motion"
import { AlertCircle, CheckCircle, Clock, ChevronRight, ChevronLeft } from "lucide-react"
import { ObservabilityLog } from "@/lib/observability"

interface ObservabilityLogsProps {
	logs: ObservabilityLog[]
	loading: boolean
	total: number
	limit: number
	offset: number
	onPageChange: (newOffset: number) => void
	onLogClick: (log: ObservabilityLog) => void
}

export function ObservabilityLogs({
	logs,
	loading,
	total,
	limit,
	offset,
	onPageChange,
	onLogClick,
}: ObservabilityLogsProps) {
	if (loading && logs.length === 0) {
		return (
			<div className="space-y-4">
				{[...Array(5)].map((_, i) => (
					<div key={i} className="h-20 animate-pulse rounded-xl border border-white/10 bg-white/5" />
				))}
			</div>
		)
	}

	return (
		<div className="space-y-4">
			<div className="overflow-hidden rounded-xl border border-white/10 bg-white/5 backdrop-blur-sm">
				<div className="grid grid-cols-12 gap-4 border-b border-white/10 bg-white/5 p-4 text-xs font-medium uppercase tracking-wider text-gray-400">
					<div className="col-span-2">Status</div>
					<div className="col-span-2">Time</div>
					<div className="col-span-2">Symbol</div>
					<div className="col-span-2">Type</div>
					<div className="col-span-2">Trigger</div>
					<div className="col-span-2 text-right">Latency</div>
				</div>

				<div className="divide-y divide-white/5">
					{logs.map((log, index) => (
						<motion.div
							key={log.id}
							initial={{ opacity: 0, y: 10 }}
							animate={{ opacity: 1, y: 0 }}
							transition={{ delay: index * 0.05 }}
							onClick={() => onLogClick(log)}
							className="group grid cursor-pointer grid-cols-12 gap-4 p-4 transition-colors hover:bg-white/5"
						>
							<div className="col-span-2 flex items-center gap-2">
								{log.status === "completed" ? (
									<CheckCircle className="h-4 w-4 text-green-500" />
								) : log.status === "failed" ? (
									<AlertCircle className="h-4 w-4 text-red-500" />
								) : (
									<Clock className="h-4 w-4 text-yellow-500" />
								)}
								<span
									className={`text-sm font-medium ${log.status === "completed"
											? "text-green-400"
											: log.status === "failed"
												? "text-red-400"
												: "text-yellow-400"
										}`}
								>
									{log.status}
								</span>
							</div>
							<div className="col-span-2 flex items-center text-sm text-gray-400">
								{format(new Date(log.created_at), "MMM d, HH:mm:ss")}
							</div>
							<div className="col-span-2 flex items-center">
								<span className="rounded bg-blue-500/10 px-2 py-1 text-xs font-medium text-blue-400">
									{log.symbol}
								</span>
							</div>
							<div className="col-span-2 flex items-center text-sm text-gray-300">
								{log.analysis_type}
							</div>
							<div className="col-span-2 flex items-center text-sm text-gray-400">
								{log.triggered_by}
							</div>
							<div className="col-span-2 flex items-center justify-end text-sm font-mono text-gray-400">
								{log.latency_ms}ms
							</div>
						</motion.div>
					))}
				</div>
			</div>

			{/* Pagination */}
			<div className="flex items-center justify-between px-4">
				<div className="text-sm text-gray-400">
					Showing {offset + 1} to {Math.min(offset + limit, total)} of {total} results
				</div>
				<div className="flex gap-2">
					<button
						onClick={() => onPageChange(Math.max(0, offset - limit))}
						disabled={offset === 0}
						className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white transition-colors hover:bg-white/10 disabled:opacity-50"
					>
						<ChevronLeft className="h-4 w-4" />
						Previous
					</button>
					<button
						onClick={() => onPageChange(offset + limit)}
						disabled={offset + limit >= total}
						className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white transition-colors hover:bg-white/10 disabled:opacity-50"
					>
						Next
						<ChevronRight className="h-4 w-4" />
					</button>
				</div>
			</div>
		</div>
	)
}
