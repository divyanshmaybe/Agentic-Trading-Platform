FROM node:18-alpine
WORKDIR /app

# Install build tools for any native deps
RUN apk add --no-cache python3 make g++ libc6-compat

# Copy package and install dependencies
COPY apps/notification_server/package.json ./apps/notification_server/package.json
RUN cd apps/notification_server && npm install --production

# Copy the app source
COPY . /app

# Default command overridden by docker-compose, but provide a fallback
CMD ["node", "apps/notification_server/src/index.js"]
