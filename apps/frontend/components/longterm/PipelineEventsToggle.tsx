"use client"

import { ChevronDown, ChevronUp } from "lucide-react"

interface PipelineEventsToggleProps {
	eventCount: number
	isExpanded: boolean
	onToggle: () => void
}

export function PipelineEventsToggle({ eventCount, isExpanded, onToggle }: PipelineEventsToggleProps) {
	return (
		<button
			onClick={onToggle}
			className="flex w-full items-center justify-between rounded-lg bg-white/8 px-4 py-3 text-left transition hover:bg-white/10 backdrop-blur-sm mb-4"
		>
			<h3 className="text-lg font-semibold text-[#fafafa]">
				Agent Actions ({eventCount})
			</h3>
			{isExpanded ? (
				<ChevronUp className="h-5 w-5 text-white/70" />
			) : (
				<ChevronDown className="h-5 w-5 text-white/70" />
			)}
		</button>
	)
}
