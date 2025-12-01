"use client"

interface Event {
	id: string
	kind?: string
	[key: string]: any
}

interface PipelineEventsListProps {
	events: Event[]
}

export function PipelineEventsList({ events }: PipelineEventsListProps) {
	return (
		<div className="w-full mt-6">
			<div className="rounded-lg border border-white/10 bg-black/20 p-4">
				<div className="mb-3 text-sm text-white/60">
					Showing {events.length} event{events.length !== 1 ? 's' : ''} (including summary)
				</div>
				<div className="max-h-[600px] overflow-y-auto">
					<div className="space-y-4">
						{events.length === 0 ? (
							<div className="text-white/60 text-sm text-center py-4">No events to display</div>
						) : (
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
						)}
					</div>
				</div>
			</div>
		</div>
	)
}
