import { DatabaseManager } from "../../../../shared/js/dbManager";
import { notificationConfig } from "../../config";

const { PrismaClient } = require("@prisma/client");

type PrismaClientType = InstanceType<typeof PrismaClient>;

const prismaClient = new PrismaClient({
  log: notificationConfig.NODE_ENV === "development" ? ["query", "error", "warn"] : ["error"],
  datasources: {
    db: {
      url: notificationConfig.DATABASE_URL || process.env.DATABASE_URL,
    },
  },
});

const db = DatabaseManager.getInstance(notificationConfig, prismaClient);

export function getPrismaClient(): PrismaClientType {
  return db.getClient() as PrismaClientType;
}

export const prisma = prismaClient;
export { db as databaseManager };

