"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { getAdminDashboard, getAdminSummary, type AdminDashboardResponse, type AdminSummaryResponse } from "@/lib/admin"

const DASHBOARD_POLL_INTERVAL = 45000 // 45 seconds (middle of 30-60s range)
const SUMMARY_POLL_INTERVAL = 7500 // 7.5 seconds (middle of 5-10s range)

interface UseAdminDashboardReturn {
  dashboard: AdminDashboardResponse | null
  summary: AdminSummaryResponse | null
  loadingDashboard: boolean
  loadingSummary: boolean
  errorDashboard: string | null
  errorSummary: string | null
  refreshDashboard: () => Promise<void>
  refreshSummary: () => Promise<void>
  lastUpdated: number | null
}

export function useAdminDashboard(): UseAdminDashboardReturn {
  const [dashboard, setDashboard] = useState<AdminDashboardResponse | null>(null)
  const [summary, setSummary] = useState<AdminSummaryResponse | null>(null)
  const [loadingDashboard, setLoadingDashboard] = useState(true)
  const [loadingSummary, setLoadingSummary] = useState(true)
  const [errorDashboard, setErrorDashboard] = useState<string | null>(null)
  const [errorSummary, setErrorSummary] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)

  const dashboardIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const summaryIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const isMountedRef = useRef(true)

  const fetchDashboard = useCallback(async () => {
    try {
      setErrorDashboard(null)
      const data = await getAdminDashboard()
      if (isMountedRef.current) {
        setDashboard(data)
        setLastUpdated(Date.now())
      }
    } catch (error) {
      if (isMountedRef.current) {
        setErrorDashboard(error instanceof Error ? error.message : "Failed to load dashboard data")
      }
    } finally {
      if (isMountedRef.current) {
        setLoadingDashboard(false)
      }
    }
  }, [])

  const fetchSummary = useCallback(async () => {
    try {
      setErrorSummary(null)
      const data = await getAdminSummary()
      if (isMountedRef.current) {
        setSummary(data)
      }
    } catch (error) {
      if (isMountedRef.current) {
        setErrorSummary(error instanceof Error ? error.message : "Failed to load summary data")
      }
    } finally {
      if (isMountedRef.current) {
        setLoadingSummary(false)
      }
    }
  }, [])

  const refreshDashboard = useCallback(async () => {
    setLoadingDashboard(true)
    await fetchDashboard()
  }, [fetchDashboard])

  const refreshSummary = useCallback(async () => {
    setLoadingSummary(true)
    await fetchSummary()
  }, [fetchSummary])

  useEffect(() => {
    isMountedRef.current = true

    // Initial fetch
    void fetchDashboard()
    void fetchSummary()

    // Setup polling intervals
    dashboardIntervalRef.current = setInterval(() => {
      void fetchDashboard()
    }, DASHBOARD_POLL_INTERVAL)

    summaryIntervalRef.current = setInterval(() => {
      void fetchSummary()
    }, SUMMARY_POLL_INTERVAL)

    return () => {
      isMountedRef.current = false
      if (dashboardIntervalRef.current) {
        clearInterval(dashboardIntervalRef.current)
      }
      if (summaryIntervalRef.current) {
        clearInterval(summaryIntervalRef.current)
      }
    }
  }, [fetchDashboard, fetchSummary])

  return {
    dashboard,
    summary,
    loadingDashboard,
    loadingSummary,
    errorDashboard,
    errorSummary,
    refreshDashboard,
    refreshSummary,
    lastUpdated,
  }
}

