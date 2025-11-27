import { getPrismaClient, databaseManager } from "./prisma/client";
import { RedisManager } from "../../../shared/js/redisManager";
import { NotificationPublisher } from "./redis/publisher";
import { NotificationConsumer } from "./kafka/consumer";

let consumer: NotificationConsumer | null = null;
let redis: RedisManager | null = null;

async function startService() {
  try {
    console.log("[Service] Starting notification ingestion service...");

    await databaseManager.connect();
    console.log("[DB] Connected to database");

    const prisma = getPrismaClient();

    redis = RedisManager.getInstance();
    await redis.connect();
    console.log("[Redis] Connected to Redis");

    const publisher = new NotificationPublisher(redis);

    consumer = new NotificationConsumer(prisma, publisher);
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


