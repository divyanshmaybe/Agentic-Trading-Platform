import { NextRequest } from "next/server"
import { createNotificationConsumer } from "@/lib/server/kafka"
import type { NotificationStreamItem } from "@/lib/notificationStreamTypes"
import { enqueueSseEvent, textEncoder } from "./lib/sse"
import { mapKafkaMessageToNotification, normalizeKafkaPayload } from "./lib/message"
import { resolveTopics } from "./lib/topics"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

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

      const emitNotification = (notification: NotificationStreamItem) => {
        enqueueSseEvent(controller, "notification", notification, isCancelled)
      }

      try {
        consumer = createNotificationConsumer()
        
        try {
          await consumer.connect()
        } catch (connectError) {
          emitError(`Failed to connect to Kafka: ${connectError instanceof Error ? connectError.message : String(connectError)}`)
          await teardownConsumer(consumer)
          closed = true
          controller.close()
          return
        }

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
                hasOriginalValue: "value" in payload,
                hasNormalizedData: Object.keys(normalizedPayload).length > 0,
                normalizedKeys: Object.keys(normalizedPayload),
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
