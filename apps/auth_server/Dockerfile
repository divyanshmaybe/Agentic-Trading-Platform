# Production Dockerfile for auth_server
FROM node:20-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy workspace configuration files
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json ./

# Copy auth_server files (including Prisma schema)
COPY apps/auth_server/package.json ./apps/auth_server/
COPY apps/auth_server/prisma ./apps/auth_server/prisma
COPY apps/auth_server ./apps/auth_server

# Copy shared dependencies
COPY shared/js ./shared/js
COPY types ./types
COPY middleware ./middleware
COPY packages ./packages

# Install all workspace dependencies first (needed for shared code compilation)
# This ensures shared/js/dbManager.ts can find @prisma/client
RUN pnpm install --no-frozen-lockfile --production=false

# Generate Prisma client for auth_server (must be done before TypeScript compilation)
# This generates the client in the workspace node_modules where TypeScript can find it
RUN pnpm --filter=auth_server run prisma:generate

# Build the auth_server (TypeScript compilation)
# Use pnpm to run build which handles workspace module resolution correctly
# The build script runs 'prisma generate && tsc' - prisma generate is idempotent
RUN pnpm --filter=auth_server run build

FROM node:20-alpine AS runner
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate
ENV NODE_ENV=production

# Copy workspace configuration
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json ./

# Copy built application from builder
COPY --from=builder /app/apps/auth_server ./apps/auth_server

# Copy shared dependencies (needed at runtime)
COPY --from=builder /app/shared/js ./shared/js
COPY types ./types
COPY middleware ./middleware
COPY packages ./packages

# Install all workspace dependencies (needed for runtime, including @prisma/client)
RUN pnpm install --no-frozen-lockfile --production=false

# Generate Prisma client (required at runtime)
RUN pnpm --filter=auth_server run prisma:generate

# Clean up pnpm store to reduce image size
RUN pnpm store prune

# Set working directory to auth_server
WORKDIR /app/apps/auth_server

# Expose port
EXPOSE 4000

# Start the server
CMD ["pnpm", "run", "start"]
