# Database Manager (Prisma)

Centralized database connection manager for microservices using Prisma and PostgreSQL.

## Overview

The `DatabaseManager` provides a convenient, singleton-based database connection manager that works seamlessly across microservices. It's designed to be as simple to use as the previous MongoDB connection manager.

## Features

- ✅ Singleton pattern for connection reuse
- ✅ Automatic connection lifecycle management
- ✅ Health check support
- ✅ Transaction support
- ✅ Raw query support
- ✅ Graceful shutdown handling
- ✅ Service-specific Prisma client support

## Usage

### Basic Usage (Default Prisma Client)

```typescript
import { DatabaseManager } from "../../shared/js/dbManager";
import { config } from "./config";

// Get database manager instance
const db = DatabaseManager.getInstance(config);

// Connect to database
await db.connect();

// Get Prisma client
const prisma = db.getClient();

// Use Prisma directly
const users = await prisma.user.findMany();
```

### Service-Specific Prisma Client

Each service can have its own Prisma schema and generated client:

```typescript
import { DatabaseManager } from "../../shared/js/dbManager";
import { PrismaClient } from "@prisma/client"; // Generated from service's schema
import { config } from "./config";

// Create service-specific Prisma client
const prismaClient = new PrismaClient({
  log: config.NODE_ENV === "development" ? ["query", "error", "warn"] : ["error"],
  datasources: {
    db: {
      url: config.DATABASE_URL,
    },
  },
});

// Initialize database manager with custom client
const db = DatabaseManager.getInstance(config, prismaClient);

// Connect
await db.connect();

// Use Prisma client
const prisma = db.getClient();
```

### With BaseApp

```typescript
import { BaseApp } from "../../shared/js/baseApp";
import { DatabaseManager } from "../../shared/js/dbManager";
import { PrismaClient } from "@prisma/client";
import { config } from "./config";

// Create Prisma client
const prismaClient = new PrismaClient({
  log: config.NODE_ENV === "development" ? ["query", "error", "warn"] : ["error"],
  datasources: {
    db: {
      url: config.DATABASE_URL,
    },
  },
});

// Get database manager
const db = DatabaseManager.getInstance(config, prismaClient);

// Initialize app
const app = new BaseApp({
  serviceName: "My Service",
  config: config,
  // ... other options
});

// Start server (db will be connected automatically)
await app.start(db, config.PORT);

// Shutdown (db will be disconnected automatically)
process.on("SIGTERM", () => app.shutdown(db));
```

## API Reference

### `DatabaseManager.getInstance(config, prismaClient?)`

Get singleton instance of the database manager.

**Parameters:**
- `config: BaseConfig` - Configuration object with `DATABASE_URL`
- `prismaClient?: PrismaClient` - Optional custom Prisma client

**Returns:** `DatabaseManager` instance

### `db.connect()`

Connect to the database.

**Returns:** `Promise<void>`

### `db.disconnect()`

Disconnect from the database.

**Returns:** `Promise<void>`

### `db.getClient()`

Get the Prisma client instance.

**Returns:** `PrismaClient`

**Throws:** Error if not connected

### `db.prismaClient`

Property accessor for Prisma client (alias for `getClient()`).

### `db.isReady()`

Check if database is connected.

**Returns:** `boolean`

### `db.healthCheck()`

Ping database to check health.

**Returns:** `Promise<boolean>`

### `db.transaction(callback)`

Execute a transaction.

**Parameters:**
- `callback: (prisma: PrismaClient) => Promise<T>`

**Returns:** `Promise<T>`

### `db.query(query, ...values)`

Execute a raw SQL query.

**Parameters:**
- `query: string` - SQL query
- `...values: any[]` - Query parameters

**Returns:** `Promise<T[]>`

### `db.execute(query, ...values)`

Execute a raw SQL command.

**Parameters:**
- `query: string` - SQL command
- `...values: any[]` - Command parameters

**Returns:** `Promise<number>` - Number of affected rows

## Setup for Each Service

1. **Create Prisma schema** in `apps/your-service/prisma/schema.prisma` or `shared/prisma/schema.prisma` (for shared schemas)

2. **Install Prisma dependencies:**
   ```bash
   pnpm add --filter your-service @prisma/client
   pnpm add -D --filter your-service prisma
   ```

3. **Generate Prisma client:**
   ```bash
   # For service-specific schema
   pnpm --filter your-service prisma:generate
   
   # For shared schema, use --schema flag in package.json scripts
   pnpm --filter your-service prisma:generate
   ```

4. **Run migrations:**
   ```bash
   # For service-specific schema
   pnpm --filter your-service prisma:migrate
   
   # For shared schema, use --schema flag in package.json scripts
   pnpm --filter your-service prisma:migrate
   ```

5. **Use in your service:**
   ```typescript
   import { DatabaseManager } from "../../shared/js/dbManager";
   import { PrismaClient } from "@prisma/client";
   ```

## Migration from MongoDB

The API is designed to be similar to the old MongoDB manager:

**Before (MongoDB):**
```typescript
const db = DatabaseManager.getInstance(config);
await db.connect();
// Use mongoose models
```

**After (Prisma):**
```typescript
const db = DatabaseManager.getInstance(config, prismaClient);
await db.connect();
const prisma = db.getClient();
// Use Prisma client
```

## Best Practices

1. **Shared or service-specific schemas** - Schemas can be in `shared/prisma/` for shared models or `apps/your-service/prisma/` for service-specific models
2. **One Prisma client per service** - Each service should use its own generated client instance
3. **Singleton pattern** - Always use `getInstance()` to get the database manager
4. **Connection lifecycle** - Let BaseApp handle connect/disconnect, or manage manually
5. **Error handling** - Always wrap database operations in try-catch blocks
6. **Transactions** - Use `db.transaction()` for multi-step operations

## Example: Auth Server

See `apps/auth_server/lib/prisma.ts` for a complete example of how to set up the database manager in a service. The auth server uses a shared Prisma schema located in `shared/prisma/schema.prisma`.

