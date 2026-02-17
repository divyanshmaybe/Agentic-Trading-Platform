"use client"

import { ChevronDown, ChevronUp } from "lucide-react"
import { useEffect, useRef, useState, useMemo } from "react"
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
	const scrollRef = useRef<HTMLDivElement>(null)
	const [autoScroll, setAutoScroll] = useState(true)
	const { getResolvedStatus } = useEventResolution(events)

	// Sort events chronologically (oldest → newest) when expanded
	const sortedEvents = useMemo(() => {
		if (!isExpanded) return []
		return events.slice().sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime())
	}, [events, isExpanded])

	// Auto-scroll to bottom when new events arrive
	useEffect(() => {
		if (isExpanded && autoScroll && scrollRef.current) {
			const el = scrollRef.current
			el.scrollTop = el.scrollHeight
		}
	}, [sortedEvents, autoScroll, isExpanded])

	// Detect user scrolling up/down
	const onScroll = () => {
		const el = scrollRef.current
		if (!el) return

		const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 5
		setAutoScroll(atBottom)
	}

	// Reset auto-scroll when expanded state changes
	useEffect(() => {
		if (isExpanded) {
			setAutoScroll(true)
		}
	}, [isExpanded])

	// Cleanup: restore body scroll on unmount
	useEffect(() => {
		return () => {
			document.body.style.overflow = "";
		};
	}, [])
	
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
					<div
						ref={scrollRef}
						onScroll={onScroll}
						onMouseEnter={() => document.body.style.overflow = "hidden"}
						onMouseLeave={() => document.body.style.overflow = ""}
						className="max-h-[600px] overflow-y-auto no-scrollbar"
					>
						<div className="space-y-4">
							{sortedEvents.length === 0 ? (
								<div className="text-white/60 text-sm text-center py-4">No events to display</div>
							) : (
								debug ? (
									sortedEvents.map((event) => (
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
										{sortedEvents.map((event) => (
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

