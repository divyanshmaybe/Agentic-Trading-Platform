import type { KafkaMessage } from "kafkajs"

import type { NotificationStreamItem } from "@/lib/notificationStreamTypes"

function formatTimestamp(input?: unknown): string {
  const dateFromInput = (() => {
    if (!input) return null
    if (typeof input === "number") {
      return new Date(input)
    }
    if (typeof input === "string") {
      const parsed = new Date(input)
      if (!Number.isNaN(parsed.getTime())) {
        return parsed
      }
      const numeric = Number(input)
      if (!Number.isNaN(numeric)) {
        return new Date(numeric)
      }
    }
    if (input instanceof Date) {
      return input
    }
    return null
  })()

  const date = dateFromInput ?? new Date()

  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  }).format(date)
}

function truncateText(text: string | undefined, maxLength = 260): string {
  if (!text) {
    return ""
  }
  if (text.length <= maxLength) {
    return text
  }
  return `${text.slice(0, maxLength - 3)}...`
}

function toNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value
  }
  if (typeof value === "string") {
    const numeric = Number(value)
    if (!Number.isNaN(numeric) && Number.isFinite(numeric)) {
      return numeric
    }
  }
  return undefined
}

function toStringValue(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim().length > 0) {
    return value
  }
  if (value instanceof Date) {
    return value.toISOString()
  }
  return undefined
}

function parseStringArray(value: unknown): string[] | undefined {
  if (Array.isArray(value)) {
    const normalized = value
      .map((entry) => (typeof entry === "string" ? entry : undefined))
      .filter((entry): entry is string => Boolean(entry && entry.trim().length > 0))
    return normalized.length ? normalized : undefined
  }

  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value)
      return parseStringArray(parsed)
    } catch {
      // not JSON encoded, ignore
    }
  }

  return undefined
}

function getHeaderString(headers: KafkaMessage["headers"], key: string): string | undefined {
  const value = headers?.[key]
  if (typeof value === "string") {
    return value
  }
  if (value instanceof Buffer) {
    return value.toString("utf8")
  }
  return undefined
}

export function normalizeKafkaPayload(payload: Record<string, unknown>): Record<string, unknown> {
  const candidateKeys = ["value", "payload", "data"]
  const visited = new Set<Record<string, unknown>>()
  const maxDepth = 10 // Prevent infinite loops
  let depth = 0

  let current: Record<string, unknown> | undefined = payload

  while (current && !visited.has(current) && depth < maxDepth) {
    visited.add(current)
    depth++
    let advanced = false

    for (const key of candidateKeys) {
      if (!(key in current)) {
        continue
      }

      const nextLayer = current[key]

      // Handle JSON string (most common case for nested value.value structures)
      if (typeof nextLayer === "string") {
        try {
          const parsed = JSON.parse(nextLayer) as unknown
          // Only continue if we parsed an object (not array or primitive)
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            current = parsed as Record<string, unknown>
            advanced = true
            break
          }
        } catch (parseError) {
          // Not valid JSON; continue to check other keys
          console.debug(`[Kafka] Failed to parse ${key} as JSON:`, parseError)
        }
      } 
      // Handle nested object structures
      else if (nextLayer && typeof nextLayer === "object" && !Array.isArray(nextLayer)) {
        // Check if this nested object has a value key with a JSON string
        const nestedObj = nextLayer as Record<string, unknown>
        if ("value" in nestedObj && typeof nestedObj.value === "string") {
          try {
            const parsed = JSON.parse(nestedObj.value) as unknown
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
              current = parsed as Record<string, unknown>
              advanced = true
              break
            }
          } catch {
            // If nested value isn't JSON, use the nested object itself
            current = nestedObj
            advanced = true
            break
          }
        } else {
          // Use the nested object as-is
          current = nestedObj
          advanced = true
          break
        }
      }
    }

    if (!advanced) {
      break
    }
  }

  if (depth >= maxDepth) {
    console.warn("[Kafka] Reached max depth while normalizing payload, returning current state")
  }

  return current ?? {}
}

export function mapKafkaMessageToNotification(
  topic: string,
  partition: number,
  payload: Record<string, unknown>,
  message: KafkaMessage,
): NotificationStreamItem {
  const baseId = payload.id ?? `${topic}-${partition}-${message.offset ?? "o"}`
  const timestamp = formatTimestamp(
    payload.generated_at ?? payload.filing_time ?? payload.timestamp ?? message.timestamp,
  )
  const topicLower = topic.toLowerCase()
  const sourceHeader = getHeaderString(message.headers, "source")

  if (topicLower.includes("nse") && topicLower.includes("signal")) {
    const signal = toNumber(payload.signal) ?? 0
    const confidence = toNumber(payload.confidence)
    const filingTime = toStringValue(payload.filing_time)
    const generatedAt = toStringValue(payload.generated_at)
    const filingUrl = toStringValue(payload.filing_url)
    const actions = filingUrl
      ? [
          {
            label: "Review Filing",
            value: filingUrl,
            href: filingUrl,
          },
        ]
      : [
          {
            label: "Review Filing",
            value: "view-filing",
          },
        ]

    return {
      id: String(baseId),
      type: "nse-signal",
      timestamp,
      topic,
      data: {
        symbol: toStringValue(payload.symbol) ?? "NSE Signal",
        filingTime,
        filingUrl,
        signal,
        explanation: toStringValue(payload.explanation),
        confidence,
        generatedAt,
        source: toStringValue(payload.source) ?? sourceHeader,
      },
      actions,
    }
  }

  if (topicLower.includes("news") && topicLower.includes("recom")) {
    const newsSourceUrl = toStringValue(payload.news_source_url)
    const generatedAt = toStringValue(payload.generated_at)

    return {
      id: String(baseId),
      type: "news-stock-recommendation",
      timestamp,
      topic,
      data: {
        sector: toStringValue(payload.sector),
        stockName: toStringValue(payload.stock_name),
        tradeSignal: toStringValue(payload.trade_signal),
        detailedAnalysis: toStringValue(payload.detailed_analysis),
        timeWindowInvestment: toStringValue(payload.time_window_investment),
        newsSource: toStringValue(payload.news_source),
        newsSourceUrl,
        provider: toStringValue(payload.provider) ?? sourceHeader,
        generatedAt,
      },
      actions: newsSourceUrl
        ? [
            {
              label: "Open Source",
              value: newsSourceUrl,
              href: newsSourceUrl,
            },
          ]
        : undefined,
    }
  }

  if (topicLower.includes("news") && topicLower.includes("sentiment")) {
    const url = toStringValue(payload.url)
    const generatedAt = toStringValue(payload.generated_at)
    const sentiment = toStringValue(payload.sentiment)?.toUpperCase()

    return {
      id: String(baseId),
      type: "news-sentiment-article",
      timestamp,
      topic,
      data: {
        stream: toStringValue(payload.stream),
        title: toStringValue(payload.title),
        content: toStringValue(payload.content),
        sentiment,
        url,
        provider: toStringValue(payload.provider) ?? sourceHeader,
        generatedAt,
      },
      actions: url
        ? [
            {
              label: "Open Article",
              value: url,
              href: url,
            },
          ]
        : undefined,
    }
  }

  if (topicLower.includes("sector") && topicLower.includes("analysis")) {
    const generatedAt = toStringValue(payload.generated_at)

    return {
      id: String(baseId),
      type: "news-sector-analysis",
      timestamp,
      topic,
      data: {
        streamCount: toNumber(payload.stream_count),
        analysis: toStringValue(payload.analysis),
        provider: toStringValue(payload.provider) ?? sourceHeader,
        generatedAt,
      },
      actions: undefined,
    }
  }

  if (topicLower.includes("risk") && topicLower.includes("alert")) {
    const generatedAt = toStringValue(payload.generated_at)
    const urls = parseStringArray(payload.urls)

    return {
      id: String(baseId),
      type: "portfolio-risk-alert",
      timestamp,
      topic,
      data: {
        ticker: toStringValue(payload.ticker),
        name: toStringValue(payload.name),
        alert: toStringValue(payload.alert),
        severity: toStringValue(payload.severity),
        urls,
        fallPercent: toNumber(payload.fall_percent),
        currentPrice: toNumber(payload.current_price),
        currentChange: toNumber(payload.current_change),
        generatedAt,
        source: toStringValue(payload.source) ?? sourceHeader,
      },
      actions: urls?.length
        ? urls.slice(0, 2).map((url, index) => ({
            label: index === 0 ? "Open Context" : `Link ${index + 1}`,
            value: url,
            href: url,
          }))
        : undefined,
    }
  }

  const fallbackBody = truncateText(
    typeof payload === "object" ? JSON.stringify(payload) : String(payload),
  )

  return {
    id: String(baseId),
    type: "generic",
    timestamp,
    topic,
    data: {
      title: `Notification from ${topic}`,
      summary: fallbackBody,
      raw: payload,
    },
    actions: undefined,
  }
}

