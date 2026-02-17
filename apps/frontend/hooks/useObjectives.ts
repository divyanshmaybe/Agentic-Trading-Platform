import { useState, useEffect } from "react"
import { fetchObjectives, type ObjectiveResponse } from "@/lib/objectiveIntake"

export function useObjectives() {
  const [objectives, setObjectives] = useState<ObjectiveResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadObjectives = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchObjectives()
      setObjectives(data)
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to fetch objectives"
      setError(errorMessage)
      console.error("Error fetching objectives:", err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadObjectives()
  }, [])

  // Get the first active objective, or most recent if no active ones
  const activeObjective = objectives.find((obj) => obj.status === "active") || objectives[0] || null

  return {
    objectives,
    activeObjective,
    loading,
    error,
    refresh: loadObjectives,
  }
}

