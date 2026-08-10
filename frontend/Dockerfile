# ---- Stage 1: Build ----
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

COPY . .

# VITE_API_BASE is empty so the browser hits /api on the same origin;
# Nginx proxies /api → backend:8000.
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}

# Phase 10 map (Mapbox GL JS). PUBLIC token only (pk.*, URL-restricted) — see
# frontend/.env.example. Left empty, MapView renders the honest
# "unavailable" state instead of a broken/blank map.
ARG VITE_MAPBOX_TOKEN=""
ENV VITE_MAPBOX_TOKEN=${VITE_MAPBOX_TOKEN}

RUN npm run build

# ---- Stage 2: Serve ----
FROM nginx:alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy Vite build output
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
