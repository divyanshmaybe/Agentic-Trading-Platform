/**
 * Prometheus Metrics for Notification Server
 *
 * Exposes Kafka consumption, processing, and delivery metrics.
 */

import * as client from "prom-client";
import * as http from "http";

// Create a Registry
export const register = new client.Registry();

// Add default metrics (CPU, memory, etc.)
client.collectDefaultMetrics({ register });

// ============================================================================
// Kafka Consumption Metrics
// ============================================================================

/**
 * Total Kafka messages consumed by topic and processing status.
 * Labels:
 *   - topic: Kafka topic name (stock_recommendation, news_sentiment, etc.)
 *   - status: "processed" | "failed" | "skipped"
 */
export const notificationKafkaMessagesTotal = new client.Counter({
  name: "notification_kafka_messages_total",
  help: "Total Kafka messages consumed",
  labelNames: ["topic", "status"],
  registers: [register],
});

/**
 * Consumer lag by topic and partition.
 * This should be updated periodically from consumer offsets.
 */
export const notificationKafkaLag = new client.Gauge({
  name: "notification_kafka_lag",
  help: "Consumer lag by topic and partition",
  labelNames: ["topic", "partition"],
  registers: [register],
});

/**
 * Time to process a single Kafka message.
 */
export const notificationProcessingDurationSeconds = new client.Histogram({
  name: "notification_processing_duration_seconds",
  help: "Time to process a Kafka message",
  labelNames: ["topic"],
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
  registers: [register],
});

// ============================================================================
// Delivery Metrics
// ============================================================================

/**
 * Notifications delivered by channel and status.
 * Labels:
 *   - channel: "redis" | "postgres"
 *   - status: "success" | "failed"
 */
export const notificationDeliveryTotal = new client.Counter({
  name: "notification_delivery_total",
  help: "Notifications delivered by channel",
  labelNames: ["channel", "status"],
  registers: [register],
});

/**
 * Total notification processing errors by topic and error type.
 */
export const notificationErrorsTotal = new client.Counter({
  name: "notification_errors_total",
  help: "Total notification processing errors",
  labelNames: ["topic", "error_type"],
  registers: [register],
});

// ============================================================================
// Low-Risk Event Metrics
// ============================================================================

/**
 * Low-risk events processed by event type and status.
 */
export const notificationLowRiskEventsTotal = new client.Counter({
  name: "notification_low_risk_events_total",
  help: "Low-risk events processed",
  labelNames: ["event_type", "status"],
  registers: [register],
});

// ============================================================================
// Batch Processing Metrics
// ============================================================================

/**
 * Size of processed message batches.
 */
export const notificationBatchSize = new client.Histogram({
  name: "notification_batch_size",
  help: "Size of processed message batches",
  labelNames: ["topic"],
  buckets: [1, 5, 10, 25, 50, 100, 250, 500],
  registers: [register],
});

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Record a processed Kafka message.
 */
export function recordMessageProcessed(
  topic: string,
  status: "processed" | "failed" | "skipped",
  durationMs?: number
): void {
  notificationKafkaMessagesTotal.labels(topic, status).inc();

  if (durationMs !== undefined && status === "processed") {
    notificationProcessingDurationSeconds.labels(topic).observe(durationMs / 1000);
  }
}

/**
 * Record a delivery attempt.
 */
export function recordDelivery(
  channel: "redis" | "postgres",
  status: "success" | "failed"
): void {
  notificationDeliveryTotal.labels(channel, status).inc();
}

/**
 * Record an error.
 */
export function recordError(
  topic: string,
  errorType: "parse_error" | "db_error" | "redis_error" | "unknown"
): void {
  notificationErrorsTotal.labels(topic, errorType).inc();
}

/**
 * Record a low-risk event.
 */
export function recordLowRiskEvent(
  eventType: string,
  status: "processed" | "failed"
): void {
  notificationLowRiskEventsTotal.labels(eventType, status).inc();
}

/**
 * Update consumer lag for a topic/partition.
 */
export function updateLag(topic: string, partition: number, lag: number): void {
  notificationKafkaLag.labels(topic, String(partition)).set(lag);
}

// ============================================================================
// Metrics HTTP Server
// ============================================================================

let metricsServer: http.Server | null = null;

/**
 * Start a standalone HTTP server for Prometheus scraping.
 * @param port Port to listen on (default: 9101)
 */
export function startMetricsServer(port: number = 9101): void {
  if (metricsServer) {
    console.warn("[Metrics] Server already running");
    return;
  }

  metricsServer = http.createServer(async (req, res) => {
    if (req.url === "/metrics" && req.method === "GET") {
      try {
        res.setHeader("Content-Type", register.contentType);
        res.end(await register.metrics());
      } catch (err) {
        res.statusCode = 500;
        res.end("Error generating metrics");
        console.error("[Metrics] Error generating metrics:", err);
      }
    } else if (req.url === "/health" && req.method === "GET") {
      res.statusCode = 200;
      res.end("OK");
    } else {
      res.statusCode = 404;
      res.end("Not Found");
    }
  });

  metricsServer.listen(port, () => {
    console.log(`[Metrics] Prometheus metrics available at http://0.0.0.0:${port}/metrics`);
  });
}

/**
 * Stop the metrics server.
 */
export function stopMetricsServer(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!metricsServer) {
      resolve();
      return;
    }

    metricsServer.close((err) => {
      if (err) {
        reject(err);
      } else {
        metricsServer = null;
        resolve();
      }
    });
  });
}
