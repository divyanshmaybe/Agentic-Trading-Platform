"use client"

import { ChevronDown, ChevronUp } from "lucide-react"
import { EventMessage } from "./EventMessage"

interface Event {
	id: string
	kind?: string
	[key: string]: any
}

interface PipelineEventsCardProps {
	events: Event[]
	isExpanded: boolean
	onToggle: () => void
}

const debug = false

export function PipelineEventsCard({ events, isExpanded, onToggle }: PipelineEventsCardProps) {
	return (
		<div className="w-full rounded-lg border border-white/10 bg-black/20 overflow-hidden">
			<button
				onClick={onToggle}
				className="flex w-full items-center justify-between px-4 py-3 text-left transition hover:bg-black/35 backdrop-blur-sm border-b border-white/10"
			>
				<h3 className="text-lg font-semibold text-[#fafafa]">
					Agent Actions ({events.length})
				</h3>
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
					<div className="max-h-[600px] overflow-y-auto">
						<div className="space-y-4">
							{events.length === 0 ? (
								<div className="text-white/60 text-sm text-center py-4">No events to display</div>
							) : (
								debug ? (
									events.map((event) => (
										<div
											key={event.id}
											className="rounded-lg border border-white/10 bg-black/25 p-4 backdrop-blur-sm"
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
											<EventMessage key={event.id} event={event} />
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

