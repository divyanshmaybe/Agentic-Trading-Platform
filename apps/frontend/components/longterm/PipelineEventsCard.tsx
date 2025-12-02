"use client"

import { ChevronDown, ChevronUp } from "lucide-react"
import { EventMessage } from "./EventMessage"
import { useEventResolution } from "./useEventResolution"
import type { LowRiskEvent } from "@/components/hooks/useLowRiskEvents"

interface PipelineEventsCardProps {
	events: LowRiskEvent[]
	isExpanded: boolean
	onToggle: () => void
}

const debug = false

export function PipelineEventsCard({ events, isExpanded, onToggle }: PipelineEventsCardProps) {
	const { getResolvedStatus } = useEventResolution(events)
	
	return (
		<div className="w-full rounded-lg border border-white/10 bg-white/8 overflow-hidden backdrop-blur-sm">
			<button
				onClick={onToggle}
				className="flex w-full items-center justify-between px-4 py-3 text-left transition backdrop-blur-sm"
			>
				<p className="text-lg font-semibold text-white/70 font-sans">
					Agent Actions ({events.length})
				</p>
				{isExpanded ? (
					<ChevronUp className="h-5 w-5 text-white/70" />
				) : (
					<ChevronDown className="h-5 w-5 text-white/70" />
				)}
			</button>

			{isExpanded && (
				<div className="p-4">
					<div className="mb-3 text-sm text-white/60">
						Showing {events.length} event{events.length !== 1 ? 's' : ''} (including summary)
					</div>
					<div className="max-h-[600px] overflow-y-auto no-scrollbar">
						<div className="space-y-4">
							{events.length === 0 ? (
								<div className="text-white/60 text-sm text-center py-4">No events to display</div>
							) : (
								debug ? (
									events.map((event) => (
										<div
											key={event.id}
											className="rounded-lg border border-white/10 bg-white/8 p-4 backdrop-blur-sm"
										>
											<div className="mb-2 text-xs font-semibold text-white/70 uppercase tracking-wide">
												{event.kind || 'Unknown'} {event.kind === 'summary' && '✓'}
											</div>
											<pre className="text-xs text-white/90 whitespace-pre-wrap wrap-break-word font-mono">
												{JSON.stringify(event, null, 2)}
											</pre>
										</div>
									))
								) : (
									<div className="space-y-3">
										{events.map((event) => (
											<EventMessage key={event.id} event={event} resolvedStatus={getResolvedStatus(event)} />
										))}
									</div>
								)
							)}
						</div>
					</div>
				</div>
			)}
		</div>
	)
}

