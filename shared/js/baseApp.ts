import express, { Application, Request, Response, NextFunction } from "express";
import morgan from "morgan";
import helmet from "helmet";
import cookieParser from "cookie-parser";
import compression from "compression";
import cors from "cors";
import createHttpError from "http-errors";
import rateLimit from "express-rate-limit";
import http from "http";
import cluster from "cluster";
import os from "os";
import { QueueManager } from "./queueManager";
import { RedisManager } from "./redisManager";

import { errorHandler } from "../../middleware/js/errorHandler";

// Helper function to sanitize objects (prevent NoSQL injection)
function sanitizeObject(obj: any): void {
  if (!obj || typeof obj !== "object") return;
  
  for (const key in obj) {
    if (key.includes("$") || key.includes(".")) {
      delete obj[key];
    } else if (typeof obj[key] === "object" && obj[key] !== null) {
      sanitizeObject(obj[key]);
    }
  }
}
import { BaseConfig } from "../../types/config";
import webSocketService from "./webSocketServer";
import { DatabaseManager } from "./dbManager";

export interface AppOptions {
  serviceName: string;
  config: BaseConfig;
  enableSockets?: boolean;
  enableSessions?: boolean;
  enableFileUpload?: boolean;
  enableQueues?: boolean;
  disableCors?: boolean; // new option, default false
  customRateLimit?: {
    windowMs: number;
    max: number;
  };
  customCors?: cors.CorsOptions;
}

export class BaseApp {
  public app: Application;
  public server?: http.Server;
  public io?: any; // Server from socket.io (optional)
  public queueManager?: QueueManager;
  private config: BaseConfig;
  private serviceName: string;

  constructor(options: AppOptions) {
    this.app = express();
    this.config = options.config;
    this.serviceName = options.serviceName;

    this.initializeMiddleware(options);

    if (options.enableSockets) {
      this.initializeSocketIO();
    }

    if (options.enableQueues) {
      this.initializeQueues();
    }
  }

  private initializeMiddleware(options: AppOptions): void {
    // Trust proxy for deployment
    this.app.set("trust proxy", 1);

    // Development logging
    if (this.config.NODE_ENV !== "production") {
      this.app.use(morgan("dev"));
    }

    // Security middleware
    this.app.disable("x-powered-by");
    this.app.use(
      helmet({
        contentSecurityPolicy: false,
      })
    );

    // Rate limiting
    const rateLimitConfig = options.customRateLimit || {
      windowMs: 15 * 60 * 1000, // 15 minutes
      max: 100,
    };

    const limiter = rateLimit({
      ...rateLimitConfig,
      message: "Too many requests from this IP, please try again later.",
      standardHeaders: true,
      legacyHeaders: false,
    });
    this.app.use("/api/", limiter);

    // CORS configuration
    const corsOptions: cors.CorsOptions = options.customCors || {
      origin: this.config.CLIENT_URL,
      credentials: true,
      optionsSuccessStatus: 200,
      methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
      allowedHeaders: ["Content-Type", "Authorization", "x-api-key"],
    };
    // Apply CORS only if not explicitly disabled (default: enabled)
    if (!options.disableCors) {
      this.app.use(cors(corsOptions));
    }

    // Body parsing middleware
    this.app.use(cookieParser() as express.RequestHandler);
    // Parse JSON bodies first
    this.app.use(express.json({ limit: "10mb" }) as express.RequestHandler);
    // Parse URL-encoded bodies
    this.app.use(
      express.urlencoded({ extended: true, limit: "10mb" }) as express.RequestHandler
    );

    // Session middleware (optional - dynamically imported)
    if (options.enableSessions) {
      this.initializeSessions();
    }

    // File upload (optional - dynamically imported)
    if (options.enableFileUpload) {
      this.initializeFileUpload();
    }

    // Health check endpoint
    this.app.get("/health", (req: Request, res: Response) => {
      res.status(200).json({
        status: "OK",
        service: this.serviceName,
        timestamp: new Date().toISOString(),
        uptime: process.uptime(),
        memory: process.memoryUsage(),
      });
    });

    // Security and optimization - basic input sanitization
    this.app.use("/", (req: any, res: any, next: any) => {
      // Basic sanitization - remove $ and . from object keys to prevent NoSQL injection
      if (req.body && typeof req.body === "object") {
        sanitizeObject(req.body);
      }
      if (req.params && typeof req.params === "object") {
        sanitizeObject(req.params);
      }
      next();
    });
    this.app.use(compression());

    // Attach socket.io to request object for route handlers (if enabled)
    if (this.io) {
      this.app.use("/", (req: any, res: any, next: any) => {
        req.io = this.io;
        next();
      });
    }
  }

  private initializeSessions(): void {
    try {
      // Dynamically import express-session only if needed
      const session = require("express-session");
      
      // Try to use Redis store if available, otherwise use memory store
      let store: any;
      try {
        const RedisStore = require("connect-redis").default;
        const { createClient } = require("redis");
        const redisClient = createClient({
          url: process.env.REDIS_URL || "redis://localhost:6379",
        });
        redisClient.connect().catch(console.error);
        store = new RedisStore({ client: redisClient });
        console.log("✅ Using Redis for session store");
      } catch (redisError) {
        // Fallback to memory store if Redis is not available
        try {
          const MemoryStore = require("memorystore")(session);
          store = new MemoryStore({
            checkPeriod: 86400000, // prune expired entries every 24h
          });
          console.log("✅ Using memory store for sessions");
        } catch (memoryError) {
          // If memorystore is not available, use default memory store
          store = undefined;
          console.log("⚠️  Using default memory store (sessions lost on restart)");
        }
      }

      const sessionConfig: any = {
        secret: this.config.SESSION_SECRET || "default-secret",
        resave: false,
        saveUninitialized: false,
        store,
        cookie: {
          secure: this.config.NODE_ENV === "production",
          httpOnly: true,
          maxAge: 1000 * 60 * 60 * 24 * 7, // 7 days
          sameSite: this.config.NODE_ENV === "production" ? "none" : "lax",
        },
      };

      this.app.use(session(sessionConfig));
      console.log("✅ Sessions initialized");
    } catch (error) {
      console.warn(
        "⚠️  express-session not installed. Sessions disabled."
      );
      console.warn("   Install express-session if you need sessions.");
    }
  }

  private initializeFileUpload(): void {
    try {
      // Dynamically import express-fileupload only if needed
      const fileUpload = require("express-fileupload");

      this.app.use(
        "/",
        fileUpload({
          useTempFiles: true,
          tempFileDir: "/tmp/",
          limits: { fileSize: 50 * 1024 * 1024 },
        }) as unknown as express.RequestHandler
      );
      console.log("✅ File upload initialized");
    } catch (error) {
      console.warn(
        "⚠️  express-fileupload not installed. File upload disabled."
      );
      console.warn("   Install express-fileupload if you need file upload support.");
    }
  }

  private initializeSocketIO(): void {
    try {
      // Dynamically import socket.io only if needed
      const { Server } = require("socket.io");
      this.server = http.createServer(this.app);
      this.io = new Server(this.server, {
        pingTimeout: 60000,
        cors: {
          origin: this.config.CLIENT_URL,
          credentials: true,
        },
      });

      // Attach socket.io to request object for route handlers
      this.app.use((req: any, res: any, next: any) => {
        req.io = this.io;
        next();
      });

      // Initialize global WebSocket service with io instance
      webSocketService.initializeWithIO(this.io);

      // Optionally: Make globally available
      (global as any).io = this.io;
      (global as any).webSocketService = webSocketService;
    } catch (error) {
      console.warn("⚠️  socket.io not installed. WebSocket features disabled.");
      console.warn("   Install socket.io if you need WebSocket support.");
    }
  }

  private async initializeQueues(): Promise<void> {
    this.queueManager = QueueManager.getInstance();
    await this.queueManager.initialize();
    (global as any).queueManager = this.queueManager;
  }

  // Method to add routes
  public addRoutes(path: string, router: express.Router): void {
    this.app.use(path, router);
  }
  public initializeErrorHandling(): void {
    // 404 handler
    this.app.use("/", ((req: Request, res: Response, next: NextFunction) => {
      next(createHttpError.NotFound(`Route ${req.originalUrl} not found`));
    }) as express.RequestHandler);

    // Global error handler
    this.app.use("/", errorHandler as unknown as express.ErrorRequestHandler);
  }

  // Method to start the server
  public listen(port: number): Promise<void> {
    return new Promise((resolve) => {
      const serverInstance = this.server || this.app;

      serverInstance.listen(port, () => {
        console.log(`🚀 ${this.serviceName} listening on port ${port}`);
        resolve();
      });
    });
  }

  // Method to add socket event handlers
  public addSocketHandlers(handler: (io: any) => void): void {
    if (this.io) {
      handler(this.io);
    } else {
      throw new Error(
        "Socket.IO not initialized. Set enableSockets: true in options."
      );
    }
  }

  // Graceful shutdown
  public async close(): Promise<void> {
    if (this.server) {
      return new Promise((resolve) => {
        this.server!.close(() => {
          console.log(`🛑 ${this.serviceName} server closed`);
          resolve();
        });
      });
    }
  }

  public async start(db: DatabaseManager | null, port: number) {
    const useCluster = process.env.USE_CLUSTER === "true";

    if (useCluster && cluster.isPrimary) {
      // Primary process - fork workers
      await this.startAsPrimary(db, port);
    } else {
      // Worker process or non-clustered mode
      await this.startAsWorker(db, port);
    }
  }

  private async startAsPrimary(db: DatabaseManager | null, port: number) {
    const numCPUs = os.availableParallelism();
    const maxWorkers = process.env.MAX_WORKERS
      ? parseInt(process.env.MAX_WORKERS, 10)
      : numCPUs;

    console.log(
      `🚀 ${this.serviceName} Primary process ${process.pid} starting`
    );
    console.log(
      `📊 Detected ${numCPUs} CPU cores, spawning ${maxWorkers} workers`
    );

    // Fork workers
    for (let i = 0; i < maxWorkers; i++) {
      const worker = cluster.fork();
      console.log(
        `👷 Worker ${worker.id} (PID: ${worker.process.pid}) spawned`
      );
    }

    // Handle worker lifecycle events
    cluster.on("online", (worker) => {
      console.log(
        `✅ Worker ${worker.id} (PID: ${worker.process.pid}) is online`
      );
    });

    cluster.on("listening", (worker, address) => {
      console.log(
        `🎧 Worker ${worker.id} (PID: ${worker.process.pid}) listening on ${address.address}:${address.port}`
      );
    });

    cluster.on("disconnect", (worker) => {
      console.log(
        `⚠️  Worker ${worker.id} (PID: ${worker.process.pid}) disconnected`
      );
    });

    cluster.on("exit", (worker, code, signal) => {
      if (worker.exitedAfterDisconnect === true) {
        console.log(
          `👋 Worker ${worker.id} (PID: ${worker.process.pid}) exited voluntarily`
        );
      } else {
        console.error(
          `💥 Worker ${worker.id} (PID: ${worker.process.pid}) died unexpectedly (${signal || code}). Restarting...`
        );

        // Respawn the worker
        const newWorker = cluster.fork();
        console.log(
          `🔄 New worker ${newWorker.id} (PID: ${newWorker.process.pid}) spawned as replacement`
        );
      }
    });

    // Graceful shutdown handler for primary
    const shutdownPrimary = async () => {
      console.log(`\n🛑 ${this.serviceName} Primary received shutdown signal`);
      console.log("📢 Gracefully shutting down all workers...");

      const workers = Object.values(cluster.workers || {});
      const shutdownPromises = workers.map((worker) => {
        return new Promise<void>((resolve) => {
          if (!worker) {
            resolve();
            return;
          }

          const timeout = setTimeout(() => {
            console.log(`⏰ Worker ${worker.id} timeout, forcing kill`);
            worker.kill("SIGKILL");
            resolve();
          }, 10000); // 10 second timeout

          worker.on("exit", () => {
            clearTimeout(timeout);
            resolve();
          });

          worker.disconnect();
          worker.kill("SIGTERM");
        });
      });

      await Promise.all(shutdownPromises);
      console.log("✅ All workers shut down successfully");
      process.exit(0);
    };

    process.on("SIGTERM", shutdownPrimary);
    process.on("SIGINT", shutdownPrimary);
  }

  private async startAsWorker(db: DatabaseManager | null, port: number) {
    try {
      // Connect to database if provided
      if (db) {
        await db.connect();
      }

      // Note: Redis connection is handled by QueueManager.initialize() if queues are enabled
      // Sessions also handle Redis connection dynamically if needed
      // No need to connect Redis here separately

      await this.listen(port);

      if (cluster.isWorker) {
        console.log(
          `🚀 ${this.serviceName} Worker ${cluster.worker?.id} (PID: ${process.pid}) started successfully`
        );
      } else {
        console.log(
          `🚀 ${this.serviceName} started successfully (PID: ${process.pid})`
        );
      }
    } catch (error) {
      console.error(`💥 Failed to start ${this.serviceName}:`, error);
      process.exit(1);
    }
  }

  public async shutdown(db: DatabaseManager | null) {
    const isWorker = cluster.isWorker;
    const processInfo = isWorker
      ? `Worker ${cluster.worker?.id} (PID: ${process.pid})`
      : `Process (PID: ${process.pid})`;

    console.log(`🛑 Shutting down ${this.serviceName} ${processInfo}...`);

    if (this.queueManager) {
      await this.queueManager.shutdown();
    }

    // Disconnect Redis
    const redisManager = RedisManager.getInstance();
    await redisManager.disconnect();

    await this.close();
    
    // Disconnect database if provided
    if (db) {
      await db.disconnect();
    }

    console.log(`✅ ${this.serviceName} ${processInfo} shutdown complete`);
    process.exit(0);
  }
}
