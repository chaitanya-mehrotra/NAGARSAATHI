# Stage 1: Build static frontend assets
FROM node:20-alpine AS builder

WORKDIR /app

# Copy root workspace and package manifests
COPY package.json package-lock.json* ./
COPY packages/contracts/package.json ./packages/contracts/
COPY apps/web/package.json ./apps/web/

# Install dependencies
RUN npm ci || npm install

# Copy contract source & build contracts
COPY packages/contracts/ ./packages/contracts/

# Copy web source and config
COPY apps/web/ ./apps/web/

# Build production bundle
WORKDIR /app/apps/web
ENV VITE_API_BASE_URL=""
RUN npm run build

# Stage 2: Serve static files via Nginx gateway
FROM nginx:1.27-alpine

# Copy custom Nginx gateway configuration
COPY infrastructure/docker/nginx.conf /etc/nginx/conf.d/default.conf

# Copy build artifacts to Nginx html directory
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
