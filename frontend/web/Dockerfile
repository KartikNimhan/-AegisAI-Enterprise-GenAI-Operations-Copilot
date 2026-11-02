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
# nginx-unprivileged: runs as the non-root user 101 (a numeric USER, so
# Kubernetes can verify `runAsNonRoot`), listens on 8080 (an unprivileged
# process cannot bind port 80), and keeps its pid file and temp directories under
# /tmp. nginx 1.30 (stable line) on Alpine 3.24; it replaced 1.27.5 on Alpine
# 3.21, whose OS packages lacked published security fixes. Multi-arch
# (amd64/arm64).
# The digest below is enforced: it is the multi-arch index digest of the
# 1.30.6-alpine tag, confirmed against the Docker Hub registry (the manifest's
# Docker-Content-Digest header, and the SHA-256 of the index body itself).
# The tag stays for readability. To update, resolve the new tag's index digest
# from the registry and replace both together.
FROM nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03 AS runtime

# The build steps below need root; the final USER drops back to 101.
USER root

# Alpine v3.24 security fixes the pinned base image predates (Trivy, runs #47
# and #53). Only these six packages change, from the image's own v3.24
# repositories; each ">=" is a floor, so the build fails instead of shipping an
# older one. nginx itself (an nginx.org build) is deliberately not upgraded.
# Remove this step once the pinned digest already contains these versions.
RUN apk add --no-cache \
        "brotli-libs>=1.2.1-r0" \
        "curl>=8.23.0-r0" \
        "libcurl>=8.23.0-r0" \
        "musl>=1.2.6-r3" \
        "musl-utils>=1.2.6-r3" \
        "zlib>=1.3.2-r1"

COPY --from=builder /srv/dist /usr/share/nginx/html
# The nginx image renders /etc/nginx/templates/*.template into conf.d at
# start (substituting ${BACKEND_UPSTREAM}); drop its stock default.conf so
# the rendered file is the only server block.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.d/10-aegis-config.sh
# Writable by the runtime user (uid 101, gid 0) at start-up without root:
#   - the html directory, because docker-entrypoint.sh writes config.js there;
#   - conf.d, because the image's template step renders default.conf there
#     (already so in this base image; repeated so the dependency is explicit).
# Group write is included so an orchestrator that assigns an arbitrary uid in
# group 0 works too. Nothing else in the root filesystem is written at runtime
# (pid file and temp paths are under /tmp).
# (`sed` removes carriage returns: a checkout with CRLF line endings, e.g.
# Windows with core.autocrlf, would otherwise make the script's `#!/bin/sh`
# unrunnable inside the Linux image.)
RUN sed -i 's/\r$//' /docker-entrypoint.d/10-aegis-config.sh /etc/nginx/templates/default.conf.template \
    && chmod +x /docker-entrypoint.d/10-aegis-config.sh \
    && chown 101:0 /usr/share/nginx/html /etc/nginx/conf.d \
    && chmod g+w /usr/share/nginx/html /etc/nginx/conf.d

USER 101

# The browser (not this container) calls the backend directly, so this
# only needs to be reachable from the host — see src/config.ts's own
# docstring on why the backend's Docker-published port is used here, not
# the internal Compose service name.
ENV API_BASE_URL=http://localhost:8000
# Where nginx forwards /api/ requests (used when API_BASE_URL is empty, i.e.
# same-origin, and available regardless). Compose service name by default.
ENV BACKEND_UPSTREAM=http://backend:8000
# Browser sign-in (public values, not secrets): the identity provider's issuer URL
# and the id of the public client registered for this app. Empty authority = the
# app shows "Sign-in is not configured" (see src/auth/).
ENV OIDC_AUTHORITY=
ENV OIDC_CLIENT_ID=aegisai-web

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O- http://127.0.0.1:8080/ >/dev/null 2>&1 || exit 1
