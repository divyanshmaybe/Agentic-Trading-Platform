FROM node:20-alpine AS builder

WORKDIR /app

# Enable pnpm via corepack
RUN corepack enable && corepack prepare pnpm@latest --activate

# Workspace manifests
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./

# Copy workspace packages that the frontend relies on
COPY packages ./packages
COPY shared ./shared
COPY types ./types

# Copy frontend source
COPY apps/frontend/package.json ./apps/frontend/
COPY apps/frontend ./apps/frontend

# Install dependencies (workspace-aware) and build
RUN pnpm install --frozen-lockfile --filter frontend... && \
    pnpm --filter frontend run build

FROM node:20-alpine AS runner

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# Copy workspace manifests needed for pnpm install
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./

# Copy required packages and frontend application
COPY packages ./packages
COPY shared ./shared
COPY types ./types
COPY apps/frontend/package.json ./apps/frontend/

# Copy build artifacts from builder stage
COPY --from=builder /app/apps/frontend/.next ./apps/frontend/.next
COPY --from=builder /app/apps/frontend/public ./apps/frontend/public

# Production install (include dev deps needed at runtime like TypeScript)
RUN pnpm install --frozen-lockfile --filter frontend... && \
    pnpm store prune

WORKDIR /app/apps/frontend

EXPOSE 3000

CMD ["pnpm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]

