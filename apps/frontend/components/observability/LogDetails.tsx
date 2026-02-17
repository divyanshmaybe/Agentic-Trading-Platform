import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { ObservabilityLog } from "@/lib/observability"
import { format } from "date-fns"
import { CheckCircle, AlertCircle, Clock, Brain, DollarSign, Zap } from "lucide-react"

interface LogDetailsProps {
	log: ObservabilityLog | null
	open: boolean
	onOpenChange: (open: boolean) => void
}

export function LogDetails({ log, open, onOpenChange }: LogDetailsProps) {
	if (!log) return null

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-4xl border-white/10 bg-[#0c0c0c] text-white sm:max-h-[90vh] overflow-y-auto">
				<DialogHeader>
					<div className="flex items-center justify-between pr-8">
						<DialogTitle className="text-xl font-bold">Analysis Details</DialogTitle>
						<div className="flex gap-2">
							<Badge variant="outline" className="border-white/20 bg-white/5">
								{log.id}
							</Badge>
							<Badge
								variant="outline"
								className={
									log.status === "completed"
										? "border-green-500/50 bg-green-500/10 text-green-400"
										: log.status === "failed"
											? "border-red-500/50 bg-red-500/10 text-red-400"
											: "border-yellow-500/50 bg-yellow-500/10 text-yellow-400"
								}
							>
								{log.status}
							</Badge>
						</div>
					</div>
				</DialogHeader>

				<div className="grid gap-6 py-4">
					{/* Header Stats */}
					<div className="grid grid-cols-2 gap-4 md:grid-cols-4">
						<div className="rounded-lg border border-white/10 bg-white/5 p-3">
							<div className="flex items-center gap-2 text-xs text-gray-400">
								<Brain className="h-3 w-3" />
								Model
							</div>
							<div className="mt-1 font-mono text-sm">{log.model_name || "N/A"}</div>
						</div>
						<div className="rounded-lg border border-white/10 bg-white/5 p-3">
							<div className="flex items-center gap-2 text-xs text-gray-400">
								<Zap className="h-3 w-3" />
								Latency
							</div>
							<div className="mt-1 font-mono text-sm">{log.latency_ms ? `${log.latency_ms}ms` : "N/A"}</div>
						</div>
						<div className="rounded-lg border border-white/10 bg-white/5 p-3">
							<div className="flex items-center gap-2 text-xs text-gray-400">
								<DollarSign className="h-3 w-3" />
								Cost
							</div>
							<div className="mt-1 font-mono text-sm">
								{log.cost_estimate ? `$${log.cost_estimate.toFixed(5)}` : "N/A"}
							</div>
						</div>
						<div className="rounded-lg border border-white/10 bg-white/5 p-3">
							<div className="flex items-center gap-2 text-xs text-gray-400">
								<Clock className="h-3 w-3" />
								Created
							</div>
							<div className="mt-1 font-mono text-sm">
								{format(new Date(log.created_at), "HH:mm:ss")}
							</div>
						</div>
					</div>

					{/* Main Content */}
					<div className="space-y-4">
						<div>
							<h4 className="mb-2 text-sm font-medium text-gray-400">Summary</h4>
							<div className="rounded-lg border border-white/10 bg-white/5 p-4 text-sm leading-relaxed text-gray-200">
								{log.summary}
							</div>
						</div>

						<div className="grid gap-4 md:grid-cols-2">
							<div>
								<h4 className="mb-2 text-sm font-medium text-gray-400">Key Findings</h4>
								<ul className="space-y-2 rounded-lg border border-white/10 bg-white/5 p-4 text-sm">
									{(log.key_findings || []).map((finding, i) => (
										<li key={i} className="flex items-start gap-2">
											<span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
											<span className="text-gray-300">{finding}</span>
										</li>
									))}
								</ul>
							</div>
							<div>
								<h4 className="mb-2 text-sm font-medium text-gray-400">Risk Factors</h4>
								<ul className="space-y-2 rounded-lg border border-white/10 bg-white/5 p-4 text-sm">
									{(log.risk_factors || []).map((risk, i) => (
										<li key={i} className="flex items-start gap-2">
											<span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" />
											<span className="text-gray-300">{risk}</span>
										</li>
									))}
								</ul>
							</div>
						</div>

						<div>
							<h4 className="mb-2 text-sm font-medium text-gray-400">Prompt</h4>
							<pre className="max-h-40 overflow-auto rounded-lg border border-white/10 bg-black/50 p-4 font-mono text-xs text-gray-400">
								{log.prompt}
							</pre>
						</div>

						{log.error_message && (
							<div>
								<h4 className="mb-2 text-sm font-medium text-red-400">Error Message</h4>
								<div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-300">
									{log.error_message}
								</div>
							</div>
						)}
					</div>
				</div>
			</DialogContent>
		</Dialog>
	)
}
