import { PrismaClient } from "@prisma/client";
import { BaseConfig } from "../../types/config";

/**
 * Prisma Database Manager
 * Centralized database connection manager for microservices using Prisma
 * 
 * Each service should generate its own Prisma client via `prisma generate`
 * and pass it to the manager, or use the default @prisma/client
 * 
 * Usage:
 * ```typescript
 * // Option 1: Use default Prisma client
 * const db = DatabaseManager.getInstance(config);
 * await db.connect();
 * const prisma = db.getClient();
 * 
 * // Option 2: Use custom Prisma client (service-specific)
 * import { PrismaClient as MyPrismaClient } from "./generated/client";
 * const db = DatabaseManager.getInstance(config, new MyPrismaClient());
 * await db.connect();
 * ```
 */
export class DatabaseManager {
  private static instance: DatabaseManager | null = null;
  private prisma: PrismaClient;
  private config: BaseConfig;
  private isConnected: boolean = false;

  private constructor(config: BaseConfig, prismaClient?: PrismaClient) {
    this.config = config;
    // Use provided client or create default one
    this.prisma = prismaClient || new PrismaClient({
      log:
        config.NODE_ENV === "development"
          ? ["query", "error", "warn"]
          : ["error"],
      datasources: {
        db: {
          url: config.DATABASE_URL || process.env.DATABASE_URL,
        },
      },
    });
  }

  /**
   * Get singleton instance of DatabaseManager
   * @param config - Base configuration with DATABASE_URL
   * @param prismaClient - Optional custom Prisma client (for service-specific schemas)
   */
  public static getInstance(
    config: BaseConfig,
    prismaClient?: PrismaClient
  ): DatabaseManager {
    if (!DatabaseManager.instance) {
      DatabaseManager.instance = new DatabaseManager(config, prismaClient);
    }
    return DatabaseManager.instance;
  }

  /**
   * Connect to database using Prisma
   */
  public async connect(): Promise<void> {
    if (this.isConnected) {
      console.log("📦 Using existing database connection");
      return;
    }

    try {
      // Test connection
      await this.prisma.$connect();
      this.isConnected = true;

      console.log("✅ Database connected successfully (Prisma)");

      // Setup event handlers
      this.setupEventHandlers();
    } catch (error) {
      console.error("❌ Database connection failed:", error);
      this.isConnected = false;
      throw error;
    }
  }

  /**
   * Disconnect from database
   */
  public async disconnect(): Promise<void> {
    if (this.prisma) {
      try {
        await this.prisma.$disconnect();
        this.isConnected = false;
        console.log("📦 Database disconnected");
      } catch (error) {
        console.error("❌ Error disconnecting from database:", error);
        throw error;
      }
    }
  }

  /**
   * Get Prisma client instance
   * @throws Error if not connected
   */
  public getClient(): PrismaClient {
    if (!this.prisma || !this.isConnected) {
      throw new Error(
        "Database not connected. Call connect() first or check connection status."
      );
    }
    return this.prisma;
  }

  /**
   * Get Prisma client directly (alias for getClient)
   * Convenience method for direct access
   */
  public get prismaClient(): PrismaClient {
    return this.getClient();
  }

  /**
   * Check if database is connected
   */
  public isReady(): boolean {
    return this.isConnected && this.prisma !== null;
  }

  /**
   * Execute a raw query
   */
  public async query<T = any>(query: string, ...values: any[]): Promise<T[]> {
    const client = this.getClient();
    return (client.$queryRawUnsafe as any)(query, ...values);
  }

  /**
   * Execute a raw command
   */
  public async execute(query: string, ...values: any[]): Promise<number> {
    const client = this.getClient();
    return (client.$executeRawUnsafe as any)(query, ...values);
  }

  /**
   * Start a transaction
   */
  public async transaction<T>(
    callback: (prisma: PrismaClient) => Promise<T>
  ): Promise<T> {
    const client = this.getClient();
    return client.$transaction(callback as any) as Promise<T>;
  }

  /**
   * Health check - ping database
   */
  public async healthCheck(): Promise<boolean> {
    try {
      if (!this.isReady()) {
        return false;
      }
      await this.prisma!.$queryRaw`SELECT 1`;
      return true;
    } catch (error) {
      console.error("❌ Database health check failed:", error);
      return false;
    }
  }

  private setupEventHandlers(): void {
    if (!this.prisma) return;

    // Handle Prisma connection errors
    process.on("beforeExit", async () => {
      await this.disconnect();
    });

    process.on("SIGINT", async () => {
      await this.disconnect();
      process.exit(0);
    });

    process.on("SIGTERM", async () => {
      await this.disconnect();
      process.exit(0);
    });
  }

  /**
   * Get connection info (for debugging)
   */
  public getConnectionInfo(): {
    connected: boolean;
  } {
    return {
      connected: this.isConnected,
    };
  }
}

/**
 * Convenience function to get database instance
 * Usage: const db = getDatabase(config);
 */
export function getDatabase(
  config: BaseConfig,
  prismaClient?: PrismaClient
): DatabaseManager {
  return DatabaseManager.getInstance(config, prismaClient);
}

/**
 * Export PrismaClient type for convenience
 */
export type { PrismaClient };
