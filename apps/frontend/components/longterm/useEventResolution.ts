import { useMemo } from "react"
import type { LowRiskEvent } from "@/components/hooks/useLowRiskEvents"

export type EffectiveStatus = "pending" | "in_progress" | "completed" | "error"

export function buildEntityKey(event: LowRiskEvent): string {
	const { kind, content } = event

	switch (kind) {
		case "stage":
			return `stage:${content?.stage || "unknown"}`
		case "industry":
			return "industry"
		case "stock":
			return `stock:${content?.content || "unknown"}`
		case "report":
			return `report:${content?.ticker || "unknown"}`
		case "summary":
			return "summary"
		case "reasoning":
			return "reasoning"
		case "info":
			return "info"
		default:
			return `unknown:${kind || "unknown"}`
	}
}

function mapStatusToEffective(status: string | null): EffectiveStatus {
	if (!status) return "pending"

	const statusLower = status.toLowerCase()

	if (statusLower === "error") {
		return "error"
	}

	if (
		statusLower === "fetching" ||
		statusLower === "start" ||
		statusLower === "generating" ||
		statusLower === "thinking" ||
		statusLower === "progress"
	) {
		return "in_progress"
	}

	if (
		statusLower === "fetched" ||
		statusLower === "generated" ||
		statusLower === "done" ||
		statusLower === "completed" ||
		statusLower === "cached"
	) {
		return "completed"
	}

	return "pending"
}

export function computeLatestStatuses(
	events: LowRiskEvent[]
): Record<string, EffectiveStatus> {
	const statusMap: Record<string, EffectiveStatus> = {}

	const sortedEvents = [...events].sort(
		(a, b) => a.createdAt.getTime() - b.createdAt.getTime()
	)

	for (const event of sortedEvents) {
		const key = buildEntityKey(event)
		const effectiveStatus = mapStatusToEffective(event.status)
		statusMap[key] = effectiveStatus
	}

	return statusMap
}

export function useEventResolution(events: LowRiskEvent[]) {
	const latestStatuses = useMemo(
		() => computeLatestStatuses(events),
		[events]
	)

	const getResolvedStatus = useMemo(
		() => (event: LowRiskEvent): EffectiveStatus => {
			const key = buildEntityKey(event)
			return latestStatuses[key] || "pending"
		},
		[latestStatuses]
	)

	return { getResolvedStatus }
}

