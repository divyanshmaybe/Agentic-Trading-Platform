"use client"

import { useEffect, useRef, useState } from "react"
import { EventMessage } from "./EventMessage"

interface Event {
	id: string
	kind?: string
	[key: string]: any
}

interface StreamingEventsViewProps {
	events: Event[]
}

const debug = false // set to true to see the raw events

export function StreamingEventsView({ events }: StreamingEventsViewProps) {
	const previousEventIdsRef = useRef<Set<string>>(new Set())
	const [newEventIds, setNewEventIds] = useState<Set<string>>(new Set())

	// Track which events are new (not seen before)
	useEffect(() => {
		const currentIds = new Set(events.map(e => e.id))
		const newIds = new Set<string>()

		// Find events that weren't in the previous set
		events.forEach(event => {
			if (!previousEventIdsRef.current.has(event.id)) {
				newIds.add(event.id)
			}
		})

		// Update the new events set
		if (newIds.size > 0) {
			setNewEventIds(newIds)
		}

		// Update previous set for next render
		previousEventIdsRef.current = currentIds

		// Clear animation class after animation completes
		const timeout = setTimeout(() => {
			setNewEventIds(new Set())
		}, 600) // Match animation duration

		return () => clearTimeout(timeout)
	}, [events])

	return (
		<div className="flex-1 overflow-hidden">
			<div className="max-h-[80vh] overflow-y-auto no-scrollbar">
				<div className="space-y-3">
				 {
					debug ? (
						events.map((event) => (
							<div
								key={event.id}
								className="rounded-lg border border-white/10 bg-white/8 p-4 backdrop-blur-sm"
							>
								<pre className="text-xs text-white/90 whitespace-pre-wrap wrap-break-word font-mono">
									{JSON.stringify(event, null, 2)}
								</pre>
							</div>
						))
					) : events.map((event) => (
						<div
							key={event.id}
							className={newEventIds.has(event.id) ? "animate-event-enter no-scrollbar" : "no-scrollbar"}
						>
							<EventMessage event={event} />
						</div>
					))
				 }
				</div>
			</div>
		</div>
	)
}
