import { Search, Filter, X } from "lucide-react"
import { FetchLogsParams } from "@/lib/observability"

interface ObservabilityFiltersProps {
	params: FetchLogsParams
	onParamChange: (params: Partial<FetchLogsParams>) => void
	symbols: string[]
	triggers: string[]
}

export function ObservabilityFilters({
	params,
	onParamChange,
	symbols,
	triggers,
}: ObservabilityFiltersProps) {
	return (
		<div className="flex flex-col gap-4 rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm md:flex-row md:items-center md:justify-between">
			<div className="flex flex-1 items-center gap-4">
				<div className="relative flex-1 md:max-w-xs">
					<Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
					<input
						type="text"
						placeholder="Search by ID or content..."
						className="w-full rounded-lg border border-white/10 bg-black/20 py-2 pl-10 pr-4 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
						onChange={(e) => {
							// Implement search logic if API supports it, or filter locally?
							// The API spec doesn't show a general search query, only specific fields.
							// For now, maybe we can map this to 'symbol' or just leave it as a placeholder for future search implementation
							// or maybe we can search by symbol if it matches?
							// Let's stick to the specific filters for now and maybe use this for symbol search if user types a valid symbol
						}}
					/>
				</div>

				<select
					value={params.status || ""}
					onChange={(e) => onParamChange({ status: e.target.value || undefined })}
					className="rounded-lg border border-white/10 bg-black/20 px-4 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
				>
					<option value="">All Statuses</option>
					<option value="completed">Completed</option>
					<option value="failed">Failed</option>
					<option value="pending">Pending</option>
				</select>

				<select
					value={params.symbol || ""}
					onChange={(e) => onParamChange({ symbol: e.target.value || undefined })}
					className="rounded-lg border border-white/10 bg-black/20 px-4 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
				>
					<option value="">All Symbols</option>
					{symbols.map((s) => (
						<option key={s} value={s}>
							{s}
						</option>
					))}
				</select>

				<select
					value={params.triggered_by || ""}
					onChange={(e) => onParamChange({ triggered_by: e.target.value || undefined })}
					className="rounded-lg border border-white/10 bg-black/20 px-4 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
				>
					<option value="">All Triggers</option>
					{triggers.map((t) => (
						<option key={t} value={t}>
							{t}
						</option>
					))}
				</select>
			</div>

			<div className="flex items-center gap-2">
				{(params.status || params.symbol || params.triggered_by) && (
					<button
						onClick={() => onParamChange({ status: undefined, symbol: undefined, triggered_by: undefined })}
						className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-red-400 hover:bg-red-500/10"
					>
						<X className="h-4 w-4" />
						Clear Filters
					</button>
				)}
			</div>
		</div>
	)
}
