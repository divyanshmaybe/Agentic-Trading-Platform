/**
 * Prisma Client for Auth Server
 * 
 * This file provides direct access to Prisma client and the database manager.
 * The Prisma client is generated from shared/prisma/schema.prisma
 * 
 * Usage:
 * ```typescript
 * import { prisma } from "./lib/prisma";
 * // or
 * import { databaseManager } from "./lib/prisma";
 * const prisma = databaseManager.getClient();
 * ```
 */
import { DatabaseManager } from "../../../shared/js/dbManager";
import { authConfig } from "../config";

// Import PrismaClient at runtime (works correctly)
const { PrismaClient } = require("@prisma/client");

// Type assertion to satisfy TypeScript - PrismaClient is available at runtime
// The generated client exports PrismaClient, but TypeScript may not resolve it correctly
// This is a known issue with pnpm and Prisma client generation
type PrismaClientType = InstanceType<typeof PrismaClient>;

// Create Prisma client instance
const prismaClient = new PrismaClient({
  log: authConfig.NODE_ENV === "development" ? ["query", "error", "warn"] : ["error"],
  datasources: {
    db: {
      url: authConfig.DATABASE_URL || process.env.DATABASE_URL,
    },
  },
});

// Get database manager instance
const db = DatabaseManager.getInstance(authConfig, prismaClient);

// Export prisma client getter (lazy access - requires connection first)
export function getPrismaClient(): PrismaClientType {
  return db.getClient() as PrismaClientType;
}

// Export prisma client for direct access (convenience)
// Note: This will throw if database is not connected
// Use getPrismaClient() or ensure db.connect() is called first
export const prisma = prismaClient;

// Re-export database manager for convenience
export { db as databaseManager };

