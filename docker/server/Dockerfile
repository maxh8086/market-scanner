# Build context is the repo root (compose context "."). Only server/ is copied.
# No .env or secrets are copied: .dockerignore excludes them, and this file never COPYs data/, secrets/ or .env.
# The healthcheck is in docker-compose.yml (the slim image has no curl).
FROM node:24-slim AS build
WORKDIR /app/server
COPY server/package.json server/package-lock.json ./
RUN npm ci
COPY server/tsconfig.json ./
COPY server/src ./src
RUN npm run build

FROM node:24-slim
ENV NODE_ENV=production
WORKDIR /app/server
COPY server/package.json server/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/server/dist ./dist
USER node
EXPOSE 8081
CMD ["node", "dist/index.js"]
