import { useEffect, useState } from "react"

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

