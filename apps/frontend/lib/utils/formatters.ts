export function parseScientificNotation(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0
  
  if (typeof value === "number") return value
  
  const str = value.trim()
  if (str === "" || str === "0") return 0
  
  const sign = str[0] === "-" ? -1 : 1
  const absStr = str.replace(/^[+-]/, "")
  
  const leadingZeros = absStr.match(/^0+/)
  if (leadingZeros && leadingZeros[0].length > 10) {
    return 0
  }
  
  const parsed = parseFloat(str)
  if (isNaN(parsed)) return 0
  
  return parsed
}

export function formatCurrency(value: string | number | null | undefined, fallback = "—"): string {
  const num = parseScientificNotation(value)
  
  if (num === 0 && (value === null || value === undefined)) return fallback
  
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(num)
}

export function formatCurrencyInteger(value: string | number | null | undefined, fallback = "—"): string {
  const num = parseScientificNotation(value)
  
  if (num === 0 && (value === null || value === undefined)) return fallback
  
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(Math.round(num))
}

export function formatNumber(value: string | number | null | undefined, fallback = "—"): string {
  const num = parseScientificNotation(value)
  
  if (num === 0 && (value === null || value === undefined)) return fallback
  
  return new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: 2,
  }).format(num)
}

export function formatPercentage(value: string | number | null | undefined, fallback = "—"): string {
  const num = parseScientificNotation(value)
  
  if (num === 0 && (value === null || value === undefined)) return fallback
  
  const formatted = (num * 100).toFixed(2)
  return `${num >= 0 ? "+" : ""}${formatted}%`
}

export function formatPercentageInteger(value: string | number | null | undefined, fallback = "—"): string {
  const num = parseScientificNotation(value)
  
  if (num === 0 && (value === null || value === undefined)) return fallback
  
  const formatted = Math.round(num * 100)
  return `${num >= 0 ? "+" : ""}${formatted}%`
}

export function formatWeight(value: string | number | null | undefined, fallback = "—"): string {
  const num = parseScientificNotation(value)
  
  if (num === 0 && (value === null || value === undefined)) return fallback
  
  return `${(num * 100).toFixed(2)}%`
}

export function displayValue(value: string | number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined) return fallback
  return String(value)
}

export function formatDuration(value: string | number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback
  
  const num = typeof value === "number" ? value : parseFloat(String(value))
  if (isNaN(num) || num === 0) return fallback
  
  // If value is >= 1000, assume it's milliseconds, otherwise seconds
  let milliseconds: number
  if (num >= 1000) {
    // Input is in milliseconds
    milliseconds = num
  } else {
    // Input is in seconds, convert to milliseconds
    milliseconds = num * 1000
  }
  
  // If less than 1000ms (1 second), show in milliseconds
  if (milliseconds < 1000) {
    return `${milliseconds.toFixed(0)}ms`
  }
  
  // Convert to seconds
  const seconds = milliseconds / 1000
  
  // If less than 60 seconds, show in seconds with 2 decimal places
  if (seconds < 60) {
    return `${seconds.toFixed(2)}s`
  }
  
  // If 60 seconds or more, show in minutes and seconds
  const minutes = Math.floor(seconds / 60)
  const secs = (seconds % 60).toFixed(0)
  return `${minutes}m ${secs}s`
}

export function formatDate(value: string | Date | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined) return fallback
  
  try {
    const date = typeof value === "string" ? new Date(value) : value
    
    if (isNaN(date.getTime())) return fallback
    
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)
    
    // Less than 1 minute
    if (diffMins < 1) return "Just now"
    
    // Less than 1 hour
    if (diffMins < 60) return `${diffMins}m ago`
    
    // Less than 24 hours
    if (diffHours < 24) return `${diffHours}h ago`
    
    // Less than 7 days
    if (diffDays < 7) return `${diffDays}d ago`
    
    // Otherwise show date
    return new Intl.DateTimeFormat("en-IN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date)
  } catch {
    return fallback
  }
}
