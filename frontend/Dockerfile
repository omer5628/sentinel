# Build React/Vite assets while online, then ship only static files to runtime.
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# Nginx serves already-built assets; Node and npm are not needed at runtime.
FROM nginx:1.28-alpine AS runtime

# Restrict envsubst to API_UPSTREAM to preserve Nginx variables ($uri, $host, etc.).
ENV API_UPSTREAM=sentinel-api:8000 \
    NGINX_ENVSUBST_FILTER='^API_UPSTREAM$'

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist/ /usr/share/nginx/html/

EXPOSE 8080
