"use client"

import { useEffect, useRef, useState, useMemo } from "react"
import { EventMessage } from "./EventMessage"
import { useEventResolution } from "./useEventResolution"
import type { LowRiskEvent } from "@/components/hooks/useLowRiskEvents"

interface StreamingEventsViewProps {
	events: LowRiskEvent[]
}

const debug = false // set to true to see the raw events

export function StreamingEventsView({ events }: StreamingEventsViewProps) {
	const previousEventIdsRef = useRef<Set<string>>(new Set())
	const [newEventIds, setNewEventIds] = useState<Set<string>>(new Set())
	const scrollRef = useRef<HTMLDivElement>(null)
	const [autoScroll, setAutoScroll] = useState(true)
	const { getResolvedStatus } = useEventResolution(events)

	// Sort events chronologically (oldest → newest)
	const sortedEvents = useMemo(() => {
		return events.slice().sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime())
	}, [events])

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

	// Auto-scroll to bottom when new events arrive
	useEffect(() => {
		if (autoScroll && scrollRef.current) {
			const el = scrollRef.current
			el.scrollTop = el.scrollHeight
		}
	}, [sortedEvents, autoScroll])

	// Detect user scrolling up/down
	const onScroll = () => {
		const el = scrollRef.current
		if (!el) return

		const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 5
		setAutoScroll(atBottom)
	}

	// Cleanup: restore body scroll on unmount
	useEffect(() => {
		return () => {
			document.body.style.overflow = "";
		};
	}, [])

	return (
		<div className="flex-1 overflow-hidden">
			<div
				ref={scrollRef}
				onScroll={onScroll}
				onMouseEnter={() => document.body.style.overflow = "hidden"}
				onMouseLeave={() => document.body.style.overflow = ""}
				className="max-h-[80vh] overflow-y-auto no-scrollbar"
			>
				<div className="space-y-3">
				 {
					debug ? (
						sortedEvents.map((event) => (
							<div
								key={event.id}
								className="rounded-lg border border-white/10 bg-white/8 p-4 backdrop-blur-sm"
							>
								<pre className="text-xs text-white/90 whitespace-pre-wrap wrap-break-word font-mono">
									{JSON.stringify(event, null, 2)}
								</pre>
							</div>
						))
					) : sortedEvents.map((event) => (
						<div
							key={event.id}
							className={newEventIds.has(event.id) ? "animate-event-enter no-scrollbar" : "no-scrollbar"}
						>
							<EventMessage event={event} resolvedStatus={getResolvedStatus(event)} />
						</div>
					))
				 }
				</div>
			</div>
		</div>
	)
}
