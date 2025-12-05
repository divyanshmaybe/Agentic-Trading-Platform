import { getPrismaClient, databaseManager } from "./prisma/client";
import { RedisManager } from "../../../shared/js/redisManager";
import { NotificationPublisher, LowRiskPublisher } from "./redis/publisher";
import { NotificationConsumer } from "./kafka/consumer";
import { startMetricsServer, stopMetricsServer } from "./metrics";

let consumer: NotificationConsumer | null = null;
let redis: RedisManager | null = null;

// Metrics server port (configurable via env, default 9201 to avoid celery worker conflict)
const METRICS_PORT = parseInt(process.env.METRICS_PORT || "9201", 10);

async function startService() {
  try {
    console.log("[Service] Starting notification ingestion service...");

    // Start Prometheus metrics server
    startMetricsServer(METRICS_PORT);

    await databaseManager.connect();
    console.log("[DB] Connected to database");

    const prisma = getPrismaClient();

    redis = RedisManager.getInstance();
    await redis.connect();
    console.log("[Redis] Connected to Redis");

    const publisher = new NotificationPublisher(redis);
    const lowRiskPublisher = new LowRiskPublisher(redis);

    consumer = new NotificationConsumer(prisma, publisher, lowRiskPublisher);
    await consumer.start();

    console.log("[Service] Notification ingestion service started successfully");
  } catch (error) {
    console.error("[Service] Failed to start service:", error);
    process.exit(1);
  }
}

async function shutdown() {
  console.log("[Service] Shutting down gracefully...");

  if (consumer) {
    await consumer.stop();
  }

  if (redis) {
    await redis.disconnect();
  }

  await databaseManager.disconnect();

  // Stop metrics server
  await stopMetricsServer();

  console.log("[Service] Shutdown complete");
  process.exit(0);
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

process.on("unhandledRejection", (reason, promise) => {
  console.error("[Service] Unhandled Rejection at:", promise, "reason:", reason);
});

process.on("uncaughtException", (error) => {
  console.error("[Service] Uncaught Exception:", error);
  shutdown();
});

startService();


