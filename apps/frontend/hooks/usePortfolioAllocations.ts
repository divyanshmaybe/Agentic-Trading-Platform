import { useEffect, useState } from "react"
import { getPortfolioAllocations } from "@/lib/portfolio"

interface AllocationItem {
  label: string
  value: number
}

export function usePortfolioAllocations() {
  const [allocations, setAllocations] = useState<AllocationItem[]>([])
  const [allocationError, setAllocationError] = useState(false)

  useEffect(() => {
    let allocationPollInterval: NodeJS.Timeout | null = null

    async function fetchAllocations() {
      try {
        const allocationsData = await getPortfolioAllocations()
        if (allocationsData.items.length > 0) {
          const filteredAllocations = allocationsData.items
            .filter(alloc => alloc.allocation_type !== "cashAvailable")

          const allocationTypeToLabel: Record<string, string> = {
            "low_risk": "Long-Term",
            "Low_Risk": "Long-Term",
            "low risk": "Long-Term",
            "Low Risk": "Long-Term",
            "high_risk": "Intraday",
            "High_Risk": "Intraday",
            "high risk": "Intraday",
            "High Risk": "Intraday",
            "alpha": "Algorithmic",
            "Alpha": "Algorithmic",
            "liquid": "Liquid",
            "Liquid": "Liquid",
          }
          
          const allocation = filteredAllocations.map((alloc, index) => {
            const formattedType = alloc.allocation_type.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())
            const label = allocationTypeToLabel[alloc.allocation_type] || 
                         allocationTypeToLabel[formattedType] || 
                         formattedType
            
            let value = parseFloat(alloc.current_weight) * 100
            
            if (index < filteredAllocations.length - 1) {
              value = Math.round(value)
            } else {
              const sumSoFar = filteredAllocations
                .slice(0, index)
                .reduce((sum, a) => sum + Math.round(parseFloat(a.current_weight) * 100), 0)
              value = 100 - sumSoFar
            }
            
            return { label, value }
          })

          setAllocations(allocation)
          setAllocationError(false)
          
          return true
        }
        return false
      } catch (err) {
        console.error("Error fetching allocations:", err)
        return false
      }
    }

    async function initializeAllocations() {
      const allocationFetched = await fetchAllocations()
      if (!allocationFetched) {
        setAllocationError(true)
      }
    }

    initializeAllocations()

    // Poll every 10 seconds continuously
    allocationPollInterval = setInterval(async () => {
      await fetchAllocations()
    }, 10000)

    return () => {
      if (allocationPollInterval) {
        clearInterval(allocationPollInterval)
      }
    }
  }, [])

  return { allocations, allocationError }
}

