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
