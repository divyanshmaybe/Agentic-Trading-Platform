# Build from monorepo root: docker build -f apps/frontend/Dockerfile -t frontend .

ARG NODE_VERSION=20.11.1-alpine

FROM node:${NODE_VERSION} AS pnpm-base

ARG PNPM_VERSION=9.10.0

ENV PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"

RUN corepack enable pnpm && corepack prepare pnpm@${PNPM_VERSION} --activate
WORKDIR /app

# -------------------------
# 1. Dependencies Layer
# -------------------------
FROM pnpm-base AS deps

COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./
COPY packages ./packages
COPY shared ./shared
COPY types ./types
COPY apps/frontend/package.json ./apps/frontend/

RUN pnpm fetch --filter frontend...

# -------------------------
# 2. Builder
# -------------------------
FROM pnpm-base AS builder

# Build arguments for Next.js public environment variables
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_AUTH_BASE_URL
ARG NEXT_PUBLIC_PORTFOLIO_API_URL
ARG NEXT_PUBLIC_PORTFOLIO_SERVER_URL
ARG NEXT_PUBLIC_ALPHACOPILOT_URL
ARG NEXT_PUBLIC_WS_URL

# Set as environment variables for Next.js build
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_AUTH_BASE_URL=${NEXT_PUBLIC_AUTH_BASE_URL}
ENV NEXT_PUBLIC_PORTFOLIO_API_URL=${NEXT_PUBLIC_PORTFOLIO_API_URL}
ENV NEXT_PUBLIC_PORTFOLIO_SERVER_URL=${NEXT_PUBLIC_PORTFOLIO_SERVER_URL}
ENV NEXT_PUBLIC_ALPHACOPILOT_URL=${NEXT_PUBLIC_ALPHACOPILOT_URL}
ENV NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}

COPY --from=deps /pnpm /pnpm
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./
COPY packages ./packages
COPY shared ./shared
COPY types ./types
COPY apps/frontend ./apps/frontend

# Avoid rebuild issues
RUN rm -f shared/prisma/.env

RUN pnpm install --offline --filter frontend... \
    && npx prisma generate --schema=./shared/prisma/schema.prisma \
    && pnpm --filter frontend run build \
    && pnpm prune --prod

# -------------------------
# 3. Runtime (optimize!)
# -------------------------
FROM node:${NODE_VERSION} AS runner

ARG PNPM_VERSION=9.10.0

ENV PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

RUN corepack enable pnpm && corepack prepare pnpm@${PNPM_VERSION} --activate

# Create user
RUN addgroup -g 1001 -S nodejs && adduser -S next -G nodejs -u 1001

WORKDIR /app

# \u26a1 FASTER: Copy files with correct ownership directly
COPY --chown=next:nodejs --from=builder /app/node_modules ./node_modules
COPY --chown=next:nodejs --from=builder /app/packages ./packages
COPY --chown=next:nodejs --from=builder /app/shared ./shared
COPY --chown=next:nodejs --from=builder /app/types ./types
COPY --chown=next:nodejs --from=builder /app/apps/frontend ./apps/frontend

USER next

WORKDIR /app/apps/frontend

EXPOSE 3000

CMD ["pnpm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
