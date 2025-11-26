import { useEffect, useState, useCallback } from "react"
import type { AgentDashboard, AgentType } from "@/lib/types/agent"

const PORTFOLIO_API_URL = process.env.NEXT_PUBLIC_PORTFOLIO_API_URL ?? "http://localhost:8000"

interface UseAgentDashboardReturn {
  data: AgentDashboard | null
  loading: boolean
  error: string | null
  isAllocating: boolean
  refetch: () => Promise<void>
}

function getClientCookie(name: string): string | null {
  const cookies = document.cookie.split("; ")
  const entry = cookies
    .map((c) => c.trim())
    .find((section) => section.startsWith(`${name}=`))
  if (!entry) return null
  const [, value] = entry.split("=")
  return value ? decodeURIComponent(value) : null
}

function getAccessToken(): string {
  if (typeof window !== "undefined") {
    const cookieToken = getClientCookie("access_token")
    if (cookieToken) return cookieToken
    const stored = localStorage.getItem("access_token")
    if (stored) return stored
  }
  throw new Error("Missing access token. Please log in again.")
}

export function useAgentDashboard(agentType: AgentType): UseAgentDashboardReturn {
  const [data, setData] = useState<AgentDashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isAllocating, setIsAllocating] = useState(false)

  const fetchAgentData = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      setIsAllocating(false)

      const token = getAccessToken()

      const response = await fetch(
        `${PORTFOLIO_API_URL}/api/portfolio/agents/${agentType}/dashboard`,
        {
          method: "GET",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
        }
      )

      if (!response.ok) {
        // Handle 404 specifically - agents are being allocated
        if (response.status === 404) {
          setIsAllocating(true)
          setError(null)
          return
        }
        throw new Error(`Failed to fetch agent data: ${response.statusText}`)
      }

      const result = await response.json()
      setData(result)
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to fetch agent data"
      setError(errorMessage)
      console.error(`[useAgentDashboard] Error fetching ${agentType} agent:`, err)
    } finally {
      setLoading(false)
    }
  }, [agentType])

  useEffect(() => {
    fetchAgentData()
  }, [fetchAgentData])

  // Poll every minute when agents are being allocated
  useEffect(() => {
    if (!isAllocating) return

    const pollInterval = setInterval(() => {
      console.log(`[useAgentDashboard] Polling for ${agentType} agent data...`)
      fetchAgentData()
    }, 60000) // Poll every 60 seconds

    return () => {
      clearInterval(pollInterval)
    }
  }, [isAllocating, agentType, fetchAgentData])

  return {
    data,
    loading,
    error,
    isAllocating,
    refetch: fetchAgentData,
  }
}

