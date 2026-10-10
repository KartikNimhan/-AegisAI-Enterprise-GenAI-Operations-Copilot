# Frontend (React/Vite) production image.
#
# Two stages: `builder` installs deps and runs the production build
# (`tsc -b && vite build`, producing static assets in dist/); `runtime`
# serves only those static files via nginx — no Node.js, no source, no
# node_modules in the shipped image. Build context is this directory
# (frontend/web), unlike the backend/Streamlit images — this app has its
# own self-contained package.json/package-lock.json, no repo-root
# dependency source of truth to reach up to.
#
# Replaces frontend/streamlit as the default Compose `frontend` service
# (see docker-compose.yml); the Streamlit app's source and Dockerfile are
# left in place, just no longer wired into the default stack.

# ---- builder -------------------------------------------------------------
FROM node:22-slim AS builder

WORKDIR /srv

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- runtime ---------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=builder /srv/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/50-aegis-config.sh
RUN chmod +x /docker-entrypoint.d/50-aegis-config.sh

# The browser (not this container) calls the backend directly, so this
# only needs to be reachable from the host — see src/config.ts's own
# docstring on why the backend's Docker-published port is used here, not
# the internal Compose service name.
ENV API_BASE_URL=http://localhost:8000

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O- http://127.0.0.1:80/ >/dev/null 2>&1 || exit 1
