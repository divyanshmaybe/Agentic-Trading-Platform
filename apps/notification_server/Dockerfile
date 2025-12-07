ARG NODE_VERSION=20.11.1-alpine

FROM node:${NODE_VERSION} AS pnpm-base

ARG PNPM_VERSION=9.10.0

ENV PNPM_HOME=/pnpm \
	PATH="${PNPM_HOME}:${PATH}"

RUN corepack enable pnpm && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /app

FROM pnpm-base AS deps

COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./
COPY packages ./packages
COPY shared/js ./shared/js
COPY shared/prisma ./shared/prisma
COPY types ./types
COPY middleware ./middleware
COPY apps/notification_server/package.json ./apps/notification_server/package.json

RUN pnpm fetch --filter notification_server...

FROM pnpm-base AS builder

RUN apk update && apk add --no-cache openssl3 openssl3-dev curl

COPY --from=deps /pnpm /pnpm
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.json turbo.json ./
COPY packages ./packages
COPY shared/js ./shared/js
COPY shared/prisma ./shared/prisma
COPY types ./types
COPY middleware ./middleware
COPY apps/notification_server ./apps/notification_server

# Remove .env from shared/prisma to avoid conflicts during Docker build
RUN rm -f shared/prisma/.env

RUN pnpm install --offline --filter notification_server... \
	&& pnpm --filter notification_server run build \
	&& pnpm prune --prod

FROM node:${NODE_VERSION} AS runner

ARG PNPM_VERSION=9.10.0

ENV PNPM_HOME=/pnpm \
	PATH="${PNPM_HOME}:${PATH}" \
	NODE_ENV=production

RUN corepack enable pnpm && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /app

COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/packages ./packages
COPY --from=builder /app/shared/js ./shared/js
COPY --from=builder /app/shared/prisma ./shared/prisma
COPY --from=builder /app/types ./types
COPY --from=builder /app/middleware ./middleware
COPY --from=builder /app/apps/notification_server ./apps/notification_server

RUN addgroup -g 1001 -S nodejs && adduser -S notification -G nodejs -u 1001 && \
	chown -R notification:nodejs /app

USER notification

WORKDIR /app/apps/notification_server

# Expose main service port and metrics port
EXPOSE 4001
EXPOSE 9201

# Default metrics port (can be overridden)
ENV METRICS_PORT=9201

CMD ["pnpm", "run", "start"]