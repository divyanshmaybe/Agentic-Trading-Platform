import { useState } from "react"
import { useObservabilityLogs, useObservabilityStats, useObservabilityMetadata } from "@/hooks/useObservability"
import { ObservabilityLog } from "@/lib/observability"
import { ObservabilityStatsDisplay } from "./ObservabilityStats"
import { ObservabilityFilters } from "./ObservabilityFilters"
import { ObservabilityLogs } from "./ObservabilityLogs"
import { LogDetails } from "./LogDetails"

export function ObservabilityDashboard() {
	const { stats, loading: statsLoading } = useObservabilityStats()
	const { logs, total, loading: logsLoading, params, updateParams } = useObservabilityLogs()
	const { symbols, triggers } = useObservabilityMetadata()

	const [selectedLog, setSelectedLog] = useState<ObservabilityLog | null>(null)
	const [detailsOpen, setDetailsOpen] = useState(false)

	const handleLogClick = (log: ObservabilityLog) => {
		setSelectedLog(log)
		setDetailsOpen(true)
	}

	return (
		<div className="space-y-6">
			<ObservabilityStatsDisplay stats={stats} loading={statsLoading} />

			<ObservabilityFilters
				params={params}
				onParamChange={updateParams}
				symbols={symbols}
				triggers={triggers}
			/>

			<ObservabilityLogs
				logs={logs}
				loading={logsLoading}
				total={total}
				limit={params.limit || 20}
				offset={params.offset || 0}
				onPageChange={(newOffset) => updateParams({ offset: newOffset })}
				onLogClick={handleLogClick}
			/>

			<LogDetails
				log={selectedLog}
				open={detailsOpen}
				onOpenChange={setDetailsOpen}
			/>
		</div>
	)
}
