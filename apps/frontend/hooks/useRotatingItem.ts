import { useEffect, useMemo, useState } from "react"

export function useRotatingItem<T>(items: T[], intervalMs: number) {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (items.length <= 1) {
      return
    }

    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % items.length)
    }, intervalMs)

    return () => window.clearInterval(timer)
  }, [items, intervalMs])

  return items[index] ?? null
}

export function useRotatingList<T>(items: T[], intervalMs: number, visibleCount: number = 3) {
  const [startIndex, setStartIndex] = useState(0)

  useEffect(() => {
    if (items.length <= visibleCount) {
      return
    }

    const timer = window.setInterval(() => {
      setStartIndex((current) => (current + 1) % items.length)
    }, intervalMs)

    return () => window.clearInterval(timer)
  }, [items, intervalMs, visibleCount])

  return useMemo(() => {
    if (items.length === 0) return []
    
    const result: T[] = []
    for (let i = 0; i < Math.min(visibleCount, items.length); i++) {
      result.push(items[(startIndex + i) % items.length])
    }
    return result
  }, [items, startIndex, visibleCount])
}
