import { z } from "zod"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function getClientCookie(name: string): string | null {
	if (typeof document === "undefined") return null
	const cookieString = document.cookie
	if (!cookieString) return null
	const entry = cookieString
		.split(";")
		.map((section) => section.trim())
		.find((section) => section.startsWith(`${name}=`))
	if (!entry) return null
	const [, value] = entry.split("=")
	return value ? decodeURIComponent(value) : null
}

function resolveAccessToken(explicitToken?: string) {
	if (explicitToken) return explicitToken
	if (typeof window !== "undefined") {
		const cookieToken = getClientCookie("access_token")
		if (cookieToken) return cookieToken
		const stored = localStorage.getItem("access_token")
		if (stored) return stored
	}
	throw new Error("Missing access token. Please log in again.")
}

export interface ObservabilityLog {
	id: string
	analysis_type: string
	symbol: string
	analysis_period: string
	prompt: string
	response: string
	model_name: string
	model_provider: string
	token_count: number
	latency_ms: number
	cost_estimate: number
	summary: string
	key_findings: string[]
	sentiment: string
	risk_factors: string[]
	recommendations: string[]
	confidence_score: number
	triggered_by: string
	worker_id: string
	status: string
	error_message: string
	created_at: string
	context_data: Record<string, any>
	metadata: Record<string, any>
}

export interface ObservabilityStats {
	total_analyses: number
	completed: number
	failed: number
	avg_latency_ms: number
	sentiment_breakdown: Record<string, number>
	symbols_analyzed: number
	recent_activity_count: number
}

export interface ObservabilityLogsResponse {
	logs: ObservabilityLog[]
	total: number
	limit: number
	offset: number
	has_more: boolean
}

export interface FetchLogsParams {
	limit?: number
	offset?: number
	analysis_type?: string
	symbol?: string
	status?: string
	sentiment?: string
	triggered_by?: string
	model_name?: string
	start_date?: string
	end_date?: string
	sort_by?: string
	sort_order?: "asc" | "desc"
}

export async function fetchObservabilityLogs(
	params: FetchLogsParams = {},
	accessToken?: string
): Promise<ObservabilityLogsResponse> {
	const token = resolveAccessToken(accessToken)
	const queryParams = new URLSearchParams()
	Object.entries(params).forEach(([key, value]) => {
		if (value !== undefined && value !== null && value !== "") {
			queryParams.append(key, value.toString())
		}
	})

	const response = await fetch(
		`${API_BASE_URL}/api/observability/logs?${queryParams.toString()}`,
		{
			headers: {
				Authorization: `Bearer ${token}`,
			},
			credentials: "include",
		}
	)

	if (!response.ok) {
		throw new Error("Failed to fetch observability logs")
	}

	return response.json()
}

export async function fetchObservabilityLog(id: string, accessToken?: string): Promise<ObservabilityLog> {
	const token = resolveAccessToken(accessToken)
	const response = await fetch(`${API_BASE_URL}/api/observability/logs/${id}`, {
		headers: {
			Authorization: `Bearer ${token}`,
		},
		credentials: "include",
	})

	if (!response.ok) {
		throw new Error("Failed to fetch observability log")
	}

	return response.json()
}

export async function fetchObservabilityStats(days: number = 7, accessToken?: string): Promise<ObservabilityStats> {
	const token = resolveAccessToken(accessToken)
	const response = await fetch(
		`${API_BASE_URL}/api/observability/stats?days=${days}`,
		{
			headers: {
				Authorization: `Bearer ${token}`,
			},
			credentials: "include",
		}
	)

	if (!response.ok) {
		throw new Error("Failed to fetch observability stats")
	}

	return response.json()
}

export async function fetchObservabilitySymbols(accessToken?: string): Promise<string[]> {
	const token = resolveAccessToken(accessToken)
	const response = await fetch(`${API_BASE_URL}/api/observability/symbols`, {
		headers: {
			Authorization: `Bearer ${token}`,
		},
		credentials: "include",
	})

	if (!response.ok) {
		throw new Error("Failed to fetch observability symbols")
	}

	return response.json()
}

export async function fetchObservabilityTriggers(accessToken?: string): Promise<string[]> {
	const token = resolveAccessToken(accessToken)
	const response = await fetch(`${API_BASE_URL}/api/observability/triggers`, {
		headers: {
			Authorization: `Bearer ${token}`,
		},
		credentials: "include",
	})

	if (!response.ok) {
		throw new Error("Failed to fetch observability triggers")
	}

	return response.json()
}
