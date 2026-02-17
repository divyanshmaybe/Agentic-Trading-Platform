import { useState, useEffect, useCallback, useRef } from "react"
import {
	fetchObservabilityLogs,
	fetchObservabilityStats,
	fetchObservabilitySymbols,
	fetchObservabilityTriggers,
	type ObservabilityLog,
	type ObservabilityStats,
	type FetchLogsParams,
} from "@/lib/observability"

const POLLING_INTERVAL = 60000 // 1 minute

export function useObservabilityLogs(initialParams: FetchLogsParams = {}) {
	const [logs, setLogs] = useState<ObservabilityLog[]>([])
	const [total, setTotal] = useState(0)
	const [loading, setLoading] = useState(true)
	const [error, setError] = useState<string | null>(null)
	const [params, setParams] = useState<FetchLogsParams>(initialParams)

	const fetchLogs = useCallback(async (isPolling = false) => {
		try {
			if (!isPolling) setLoading(true)
			const data = await fetchObservabilityLogs(params)
			setLogs(data.logs)
			setTotal(data.total)
			setError(null)
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to fetch logs")
		} finally {
			if (!isPolling) setLoading(false)
		}
	}, [params])

	useEffect(() => {
		fetchLogs()

		const intervalId = setInterval(() => {
			fetchLogs(true)
		}, POLLING_INTERVAL)

		return () => clearInterval(intervalId)
	}, [fetchLogs])

	const updateParams = (newParams: Partial<FetchLogsParams>) => {
		setParams((prev) => ({ ...prev, ...newParams }))
	}

	return { logs, total, loading, error, params, updateParams, refresh: () => fetchLogs(false) }
}

export function useObservabilityStats(days: number = 7) {
	const [stats, setStats] = useState<ObservabilityStats | null>(null)
	const [loading, setLoading] = useState(true)
	const [error, setError] = useState<string | null>(null)

	const fetchStats = useCallback(async (isPolling = false) => {
		try {
			if (!isPolling) setLoading(true)
			const data = await fetchObservabilityStats(days)
			setStats(data)
			setError(null)
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to fetch stats")
		} finally {
			if (!isPolling) setLoading(false)
		}
	}, [days])

	useEffect(() => {
		fetchStats()

		const intervalId = setInterval(() => {
			fetchStats(true)
		}, POLLING_INTERVAL)

		return () => clearInterval(intervalId)
	}, [fetchStats])

	return { stats, loading, error, refresh: () => fetchStats(false) }
}

export function useObservabilityMetadata() {
	const [symbols, setSymbols] = useState<string[]>([])
	const [triggers, setTriggers] = useState<string[]>([])
	const [loading, setLoading] = useState(true)
	const [error, setError] = useState<string | null>(null)

	useEffect(() => {
		const fetchData = async () => {
			try {
				setLoading(true)
				const [symbolsData, triggersData] = await Promise.all([
					fetchObservabilitySymbols(),
					fetchObservabilityTriggers(),
				])
				setSymbols(symbolsData)
				setTriggers(triggersData)
			} catch (err) {
				setError(err instanceof Error ? err.message : "Failed to fetch metadata")
			} finally {
				setLoading(false)
			}
		}

		fetchData()
	}, [])

	return { symbols, triggers, loading, error }
}
