"use client"

interface Event {
	id: string
	kind?: string
	[key: string]: any
}

interface StreamingEventsViewProps {
	events: Event[]
}

export function StreamingEventsView({ events }: StreamingEventsViewProps) {
	return (
		<div className="flex-1 overflow-hidden">
			<h3 className="text-lg font-semibold mb-4 text-[#fafafa]">Live Pipeline Events</h3>
			<div className="max-h-[600px] overflow-y-auto">
				{events.length === 0 ? (
					<div className="text-white/60 text-sm">Waiting for events...</div>
				) : (
					<div className="space-y-4">
						{events.map((event) => (
							<div
								key={event.id}
								className="rounded-lg border border-white/10 bg-black/25 p-4 backdrop-blur-sm"
							>
								<pre className="text-xs text-white/90 whitespace-pre-wrap wrap-break-word font-mono">
									{JSON.stringify(event, null, 2)}
								</pre>
							</div>
						))}
					</div>
				)}
			</div>
		</div>
	)
}
