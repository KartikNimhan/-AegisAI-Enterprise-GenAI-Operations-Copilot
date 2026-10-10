#!/bin/sh
# Runs automatically before nginx starts (nginx:1.27-alpine executes every
# executable script in /docker-entrypoint.d/). Writes config.js from the
# API_BASE_URL env var so the same built image can point at a different
# backend per deployment without a rebuild — see src/config.ts.
set -eu

cat > /usr/share/nginx/html/config.js <<EOF
window.__AEGIS_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" };
EOF
