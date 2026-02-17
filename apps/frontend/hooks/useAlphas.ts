import { useState, useEffect, useCallback, useRef } from "react"

import { apiClient } from "@/lib/api"

export type LiveAlpha = {
  id: string
  name: string
  hypothesis: string | null
  run_id: string | null
  workflow_config: Record<string, unknown>
  symbols: string[]
  model_type: string | null
  strategy_type: string
  status: string
  allocated_amount: number
  portfolio_id: string
  agent_id: string | null
  last_signal_at: string | null
  total_signals: number
  created_at: string
  updated_at: string
}

export type LiveAlphaListResponse = {
  alphas: LiveAlpha[]
  total: number
}

export type CreateLiveAlphaRequest = {
  name: string
  run_id?: string
  hypothesis?: string
  workflow_config: Record<string, unknown>
  symbols: string[]
  allocated_amount: number
  portfolio_id: string
  model_type?: string
  strategy_type?: string
}

export type SignalGenerationTaskResponse = {
  task_id: string
  status: string
  alpha_id: string | null
  message: string
}

export type TaskStatusResponse = {
  task_id: string
  status: "PENDING" | "STARTED" | "PROGRESS" | "SUCCESS" | "FAILURE" | "RETRY" | "REVOKED"
  result: Record<string, unknown> | null
  error: string | null
  started_at: string | null
  completed_at: string | null
  // Progress info (when status is PROGRESS)
  step: string | null  // loading_data, computing_factors, loading_model, running_model, generating_signals, saving_signals
  progress: number | null  // 0-100
  message: string | null  // Human-readable progress message
}

export type AlphaCopilotRun = {
  id: string
  hypothesis: string
  status: string
  config: Record<string, unknown>
  num_iterations: number
  current_iteration: number
  created_at: string
  updated_at: string
  error_message?: string
  generated_factors?: Array<Record<string, unknown>> | null
  workflow_config?: Record<string, unknown> | null
  best_factors?: Array<Record<string, unknown>> | null
}

export type AlphaCopilotResult = {
  run_id: string
  status: string
  final_metrics: Record<string, unknown> | null
  all_factors: Array<Record<string, unknown>> | null
  best_factors: Array<Record<string, unknown>> | null
  workflow_config: Record<string, unknown> | null
}

export function useAlphas(portfolioId?: string) {
  const [alphas, setAlphas] = useState<LiveAlpha[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const hasInitialDataRef = useRef(false)

  const fetchAlphas = useCallback(async (isPolling = false) => {
    try {
      // Only show loading on initial fetch, not on polls when data exists
      if (!isPolling || !hasInitialDataRef.current) {
        setLoading(true)
      }
      const params = portfolioId ? `?portfolio_id=${portfolioId}` : ""
      const response = await apiClient.get<LiveAlphaListResponse>(`/api/alphas/live${params}`)
      setAlphas(response.alphas)
      setError(null)
      hasInitialDataRef.current = true
    } catch (err) {
      console.error("Failed to fetch alphas:", err)
      setError(err instanceof Error ? err.message : "Failed to fetch alphas")
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => {
    fetchAlphas(false)

    // Poll every 10 seconds
    const pollInterval = setInterval(() => {
      fetchAlphas(true)
    }, 10000)

    return () => {
      clearInterval(pollInterval)
    }
  }, [fetchAlphas])

  const createAlpha = async (data: CreateLiveAlphaRequest): Promise<LiveAlpha> => {
    const response = await apiClient.post<LiveAlpha>("/api/alphas/live", data)
    await fetchAlphas()
    return response
  }

  const startAlpha = async (alphaId: string): Promise<LiveAlpha> => {
    const response = await apiClient.post<LiveAlpha>(`/api/alphas/live/${alphaId}/start`)
    await fetchAlphas()
    return response
  }

  const stopAlpha = async (alphaId: string): Promise<LiveAlpha> => {
    const response = await apiClient.post<LiveAlpha>(`/api/alphas/live/${alphaId}/stop`)
    await fetchAlphas()
    return response
  }

  const deleteAlpha = async (alphaId: string): Promise<void> => {
    await apiClient.delete(`/api/alphas/live/${alphaId}`)
    await fetchAlphas()
  }

  // Trigger signal generation for a specific alpha
  const triggerSignals = async (alphaId: string): Promise<SignalGenerationTaskResponse> => {
    const response = await apiClient.post<SignalGenerationTaskResponse>(
      `/api/alphas/live/${alphaId}/trigger-signals`
    )
    return response
  }

  // Trigger signal generation for all running alphas
  const triggerAllSignals = async (): Promise<SignalGenerationTaskResponse> => {
    const response = await apiClient.post<SignalGenerationTaskResponse>(
      `/api/alphas/trigger-all-signals`
    )
    return response
  }

  // Get task status
  const getTaskStatus = async (taskId: string): Promise<TaskStatusResponse> => {
    const response = await apiClient.get<TaskStatusResponse>(
      `/api/alphas/tasks/${taskId}/status`
    )
    return response
  }

  return {
    alphas,
    loading,
    error,
    refetch: fetchAlphas,
    createAlpha,
    startAlpha,
    stopAlpha,
    deleteAlpha,
    triggerSignals,
    triggerAllSignals,
    getTaskStatus,
  }
}

// Helper function to get auth headers for alphacopilot requests
function getAlphaCopilotAuthHeaders(): HeadersInit {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  }
  
  if (typeof window !== "undefined") {
    // Get token from cookie first, then localStorage
    let token: string | null = null
    const cookies = document.cookie.split("; ")
    const entry = cookies
      .map((c) => c.trim())
      .find((section) => section.startsWith("access_token="))
    if (entry) {
      const [, value] = entry.split("=")
      token = value ? decodeURIComponent(value) : null
    }
    if (!token) {
      token = localStorage.getItem("access_token")
    }
    if (token) {
      headers["Authorization"] = `Bearer ${token}`
    }
  }
  
  return headers
}

export function useAlphaCopilotRuns() {
  const [runs, setRuns] = useState<AlphaCopilotRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const hasInitialDataRef = useRef(false)

  const ALPHACOPILOT_URL = process.env.NEXT_PUBLIC_ALPHACOPILOT_URL || "http://localhost:8069"

  const fetchRuns = useCallback(async (isPolling = false) => {
    try {
      // Only show loading on initial fetch, not on polls when data exists
      if (!isPolling || !hasInitialDataRef.current) {
        setLoading(true)
      }
      const response = await fetch(`${ALPHACOPILOT_URL}/runs`, {
        method: "GET",
        headers: getAlphaCopilotAuthHeaders(),
        credentials: "include",
      })
      if (!response.ok) {
        throw new Error("Failed to fetch runs")
      }
      const data = await response.json()
      setRuns(data.runs || [])
      setError(null)
      hasInitialDataRef.current = true
    } catch (err) {
      console.error("Failed to fetch AlphaCopilot runs:", err)
      setError(err instanceof Error ? err.message : "Failed to fetch runs")
    } finally {
      setLoading(false)
    }
  }, [ALPHACOPILOT_URL])

  useEffect(() => {
    fetchRuns(false)

    // Poll every 10 seconds
    const pollInterval = setInterval(() => {
      fetchRuns(true)
    }, 10000)

    return () => {
      clearInterval(pollInterval)
    }
  }, [fetchRuns])

  const createRun = async (hypothesis: string, config: Record<string, unknown> = {}): Promise<AlphaCopilotRun[]> => {
    const response = await fetch(`${ALPHACOPILOT_URL}/runs`, {
      method: "POST",
      headers: getAlphaCopilotAuthHeaders(),
      credentials: "include",
      body: JSON.stringify({
        hypothesis,
        ...config,
      }),
    })

    if (!response.ok) {
      throw new Error("Failed to create run")
    }

    const data = await response.json()
    await fetchRuns()
    return data.runs
  }

  const getRunStatus = async (runId: string): Promise<{ status: string; progress_percent: number }> => {
    const response = await fetch(`${ALPHACOPILOT_URL}/runs/${runId}/status`, {
      method: "GET",
      headers: getAlphaCopilotAuthHeaders(),
      credentials: "include",
    })
    if (!response.ok) {
      throw new Error("Failed to get run status")
    }
    return response.json()
  }

  const getRunResults = async (runId: string): Promise<AlphaCopilotResult> => {
    const response = await fetch(`${ALPHACOPILOT_URL}/runs/${runId}/results`, {
      method: "GET",
      headers: getAlphaCopilotAuthHeaders(),
      credentials: "include",
    })
    if (!response.ok) {
      throw new Error("Failed to get run results")
    }
    return response.json()
  }

  return {
    runs,
    loading,
    error,
    refetch: fetchRuns,
    createRun,
    getRunStatus,
    getRunResults,
  }
}

// Convert LiveAlpha to TopAlpha format for display
export function alphaToTopAlpha(alpha: LiveAlpha) {
  // Calculate return percentage based on signals/performance
  // For now, use a placeholder calculation
  const returnPct = alpha.total_signals > 0 ? Math.random() * 20 - 5 : 0

  return {
    id: alpha.id,
    name: alpha.name,
    returnPct,
    direction: returnPct >= 0 ? ("up" as const) : ("down" as const),
    status: alpha.status,
    totalSignals: alpha.total_signals,
    allocatedAmount: alpha.allocated_amount,
    strategyType: alpha.strategy_type,
  }
}

// Hook to poll task status until completion
export function useTaskStatus(
  taskId: string | null,
  onComplete?: (result: TaskStatusResponse) => void,
  pollInterval = 2000
) {
  const [status, setStatus] = useState<TaskStatusResponse | null>(null)
  const [isPolling, setIsPolling] = useState(false)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    setIsPolling(false)
  }, [])

  const checkStatus = useCallback(async () => {
    if (!taskId) return

    try {
      const response = await apiClient.get<TaskStatusResponse>(
        `/api/alphas/tasks/${taskId}/status`
      )
      setStatus(response)

      // Stop polling if task is complete
      if (["SUCCESS", "FAILURE", "REVOKED"].includes(response.status)) {
        stopPolling()
        onComplete?.(response)
      }
    } catch (err) {
      console.error("Failed to fetch task status:", err)
      stopPolling()
    }
  }, [taskId, stopPolling, onComplete])

  useEffect(() => {
    if (!taskId) {
      setStatus(null)
      return
    }

    // Start polling
    setIsPolling(true)
    checkStatus() // Check immediately

    intervalRef.current = setInterval(checkStatus, pollInterval)

    return () => {
      stopPolling()
    }
  }, [taskId, checkStatus, pollInterval, stopPolling])

  return {
    status,
    isPolling,
    stopPolling,
  }
}



