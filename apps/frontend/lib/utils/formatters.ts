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

export function formatWeight(value: string | number | null | undefined, fallback = "—"): string {
  const num = parseScientificNotation(value)
  
  if (num === 0 && (value === null || value === undefined)) return fallback
  
  return `${(num * 100).toFixed(2)}%`
}

export function displayValue(value: string | number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined) return fallback
  return String(value)
}

