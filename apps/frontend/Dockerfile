# Build from monorepo root: docker build -f apps/frontend/Dockerfile -t frontend .
# NOT from apps/frontend directory

ARG NODE_VERSION=20.11.1-alpine

FROM node:${NODE_VERSION} AS pnpm-base

ARG PNPM_VERSION=9.10.0

ENV PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"

RUN corepack enable pnpm && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /app

FROM pnpm-base AS deps

COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./
COPY packages ./packages
COPY shared ./shared
COPY types ./types
COPY apps/frontend/package.json ./apps/frontend/package.json

RUN pnpm fetch --filter frontend...

FROM pnpm-base AS builder

COPY --from=deps /pnpm /pnpm
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./
COPY packages ./packages
COPY shared ./shared
COPY types ./types
COPY apps/frontend ./apps/frontend

# Remove .env from shared/prisma to avoid conflicts during Docker build
RUN rm -f shared/prisma/.env

RUN pnpm install --offline --filter frontend... \
    && npx prisma generate --schema=./shared/prisma/schema.prisma \
    && pnpm --filter frontend run build \
    && pnpm prune --prod

FROM node:${NODE_VERSION} AS runner

ARG PNPM_VERSION=9.10.0

ENV PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

RUN corepack enable pnpm && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /app

COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/packages ./packages
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/types ./types
COPY --from=builder /app/apps/frontend ./apps/frontend

RUN addgroup -g 1001 -S nodejs && adduser -S next -G nodejs -u 1001 && \
    chown -R next:nodejs /app

USER next

WORKDIR /app/apps/frontend

EXPOSE 3000

CMD ["pnpm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]

