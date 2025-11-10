import { NextRequest } from "next/server"
import type { KafkaMessage } from "kafkajs"

import { createNotificationConsumer } from "@/lib/server/kafka"
import type { NotificationItem } from "@/lib/dashboardTypes"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

const textEncoder = new TextEncoder()

const DEFAULT_TOPICS = [
  process.env.NSE_FILINGS_SIGNAL_TOPIC ?? "nse_filings_trading_signal",
  process.env.NEWS_STOCK_RECOMMENDATIONS_TOPIC ?? "news_pipeline_stock_recomendations",
  process.env.NEWS_SENTIMENT_ARTICLES_TOPIC ?? "news_pipeline_sentiment_articles",
  process.env.NEWS_SECTOR_ANALYSIS_TOPIC ?? "news_pipeline_sector_analysis",
  process.env.PORTFOLIO_RISK_ALERTS_TOPIC ?? process.env.RISK_ALERTS_TOPIC ?? undefined,
].filter((topic): topic is string => Boolean(topic))

type StreamController = ReadableStreamDefaultController<Uint8Array>

function resolveTopics(request: NextRequest): string[] {
  const topicsParam = request.nextUrl.searchParams.get("topics")
  const topics = topicsParam
    ? topicsParam.split(",").map((topic) => topic.trim()).filter(Boolean)
    : DEFAULT_TOPICS

  const uniqueTopics = Array.from(new Set(topics))
  if (!uniqueTopics.length) {
    throw new Error("No Kafka topics configured for notification streaming")
  }

  return uniqueTopics
}

function enqueueSseEvent(
  controller: StreamController,
  event: string,
  data: unknown,
  cancelled: () => boolean,
): void {
  if (cancelled()) {
    return
  }

  try {
    const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
    controller.enqueue(textEncoder.encode(payload))
    console.log("[SSE] Event enqueued:", event, data)
  } catch (error) {
    console.warn("[SSE] Failed to enqueue event:", error)
  }
}

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

function normalizeKafkaPayload(payload: Record<string, unknown>): Record<string, unknown> {
  const candidateKeys = ["value", "payload", "data"]
  const visited = new Set<Record<string, unknown>>()

  let current: Record<string, unknown> | undefined = payload

  while (current && !visited.has(current)) {
    visited.add(current)
    let advanced = false

    for (const key of candidateKeys) {
      if (!(key in current)) {
        continue
      }

      const nextLayer = current[key]

      if (typeof nextLayer === "string") {
        try {
          current = JSON.parse(nextLayer) as Record<string, unknown>
          advanced = true
          break
        } catch {
          // Not JSON; move on to other keys.
        }
      } else if (nextLayer && typeof nextLayer === "object" && !Array.isArray(nextLayer)) {
        current = nextLayer as Record<string, unknown>
        advanced = true
        break
      }
    }

    if (!advanced) {
      break
    }
  }

  return current ?? {}
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

function mapKafkaMessageToNotification(
  topic: string,
  partition: number,
  payload: Record<string, unknown>,
  message: KafkaMessage,
): NotificationItem {
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

async function teardownConsumer(consumer: ReturnType<typeof createNotificationConsumer> | null) {
  if (!consumer) {
    return
  }
  try {
    await consumer.stop()
  } catch (error) {
    // Kafka may already consider the consumer stopped; ignore.
    console.warn("[Kafka] Error stopping consumer:", error)
  }

  try {
    await consumer.disconnect()
  } catch (error) {
    console.warn("[Kafka] Error disconnecting consumer:", error)
  }
}

export async function GET(request: NextRequest) {
  let topics: string[]
  try {
    topics = resolveTopics(request)
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to resolve topics"
    return new Response(JSON.stringify({ error: message }), {
      status: 500,
      headers: { "content-type": "application/json" },
    })
  }

  let consumer: ReturnType<typeof createNotificationConsumer> | null = null
  let keepAliveTimer: NodeJS.Timeout | null = null
  let closed = false

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const isCancelled = () => closed
      controller.enqueue(textEncoder.encode("retry: 5000\n\n"))

      const emitStatus = (status: string, details?: Record<string, unknown>) => {
        enqueueSseEvent(controller, "status", { status, ...(details ?? {}) }, isCancelled)
      }

      const emitError = (error: unknown) => {
        const message = error instanceof Error ? error.message : String(error)
        enqueueSseEvent(controller, "error", { message }, isCancelled)
      }

      const emitNotification = (notification: NotificationItem) => {
        enqueueSseEvent(controller, "notification", notification, isCancelled)
      }

      try {
        consumer = createNotificationConsumer()
        await consumer.connect()

        const subscribedTopics: string[] = []
        for (const topic of topics) {
          try {
            await consumer.subscribe({ topic, fromBeginning: false })
            subscribedTopics.push(topic)
          } catch (error) {
            emitError(`Failed to subscribe to topic "${topic}": ${error instanceof Error ? error.message : error}`)
          }
        }

        if (!subscribedTopics.length) {
          emitError("Unable to subscribe to any Kafka topics for notifications.")
          await teardownConsumer(consumer)
          closed = true
          controller.close()
          return
        }

        emitStatus("subscribed", { topics: subscribedTopics })

        keepAliveTimer = setInterval(() => {
          enqueueSseEvent(controller, "ping", { ts: Date.now() }, isCancelled)
        }, 15000)

        await consumer.run({
          autoCommit: true,
          eachMessage: async ({ topic, partition, message }) => {
            if (closed) {
              return
            }
            if (!message.value) {
              return
            }

            try {
              const rawMessage = message.value.toString("utf8")
              let payload: Record<string, unknown>
              try {
                payload = JSON.parse(rawMessage) as Record<string, unknown>
              } catch (parseError) {
                console.error("[Kafka] Failed to parse message value as JSON:", {
                  topic,
                  partition,
                  offset: message.offset,
                  rawMessage,
                  error: parseError,
                })
                return
              }

              const normalizedPayload = normalizeKafkaPayload(payload)
              console.log("[Kafka] Parsed notification payload:", {
                topic,
                partition,
                offset: message.offset,
                originalPayload: payload,
                normalizedPayload,
              })

              const notification = mapKafkaMessageToNotification(
                topic,
                partition,
                normalizedPayload,
                message,
              )
              emitNotification(notification)
            } catch (error) {
              emitError(
                `Failed to process message from topic "${topic}": ${
                  error instanceof Error ? error.message : String(error)
                }`,
              )
            }
          },
        })
      } catch (error) {
        emitError(error)
        closed = true
        await teardownConsumer(consumer)
        controller.close()
      }
    },
    async cancel() {
      if (closed) {
        return
      }
      closed = true
      if (keepAliveTimer) {
        clearInterval(keepAliveTimer)
      }
      await teardownConsumer(consumer)
    },
  })

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-store",
      connection: "keep-alive",
      pragma: "no-cache",
    },
  })
}
