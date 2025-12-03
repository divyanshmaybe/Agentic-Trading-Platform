import { BaseApp } from "../../shared/js/baseApp";
import { QueueManager } from "../../shared/js/queueManager";
import { authConfig } from "./config";
import { databaseManager } from "./lib/prisma";
import { authRoutes } from "./routes/auth.routes";
import { internalRoutes } from "./routes/internal.routes";
import { userRoutes } from "./routes/user.routes";
import { setupAuthQueues } from "./queue.setup";
import { allowedOrigins } from "./config";
import { prometheusMiddleware, metricsEndpoint } from "./utils/prometheusMetrics";
import { Router } from "express";

// Initialize queue manager
const queueManager = QueueManager.getInstance();

// Initialize app with auth-specific configuration
const app = new BaseApp({
  serviceName: "AgentInvest Auth Service",
  config: authConfig,
  enableSessions: true,
  enableFileUpload: false,
  enableQueues: true,
  customRateLimit: {
    windowMs: 15 * 60 * 1000,
    max: 500,
  },
  customCors: {
    origin: allowedOrigins,
    credentials: true,
    optionsSuccessStatus: 200,
    methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization", "x-api-key"],
  },
});

// Add Prometheus metrics middleware (before routes)
app.app.use(prometheusMiddleware);

// Add Prometheus metrics endpoint
const metricsRouter = Router();
metricsRouter.get("/", metricsEndpoint);
app.addRoutes("/metrics", metricsRouter);

// Setup routes
app.addRoutes("/api/auth", authRoutes);
app.addRoutes("/api/user", userRoutes);
app.addRoutes("/api/internal", internalRoutes);
app.initializeErrorHandling();

// Start server and initialize auth-specific queues
async function startServer() {
  await app.start(databaseManager, authConfig.PORT);

  if (app.queueManager) {
    await setupAuthQueues(app.queueManager);
  }
}

startServer().catch((error) => {
  console.error("Failed to start server:", error);
  process.exit(1);
});

process.on("SIGTERM", () => app.shutdown(databaseManager));
process.on("SIGINT", () => app.shutdown(databaseManager));
