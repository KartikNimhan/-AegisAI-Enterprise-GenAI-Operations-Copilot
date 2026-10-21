#!/bin/sh
# Runs before nginx starts (the nginx base image executes every executable
# script in /docker-entrypoint.d/ in name order; this one is named to run
# before the image's own template rendering). It
#   1. validates the two settings that end up inside generated text, and
#   2. writes config.js from API_BASE_URL, OIDC_AUTHORITY and OIDC_CLIENT_ID so
#      the same built image can point at a different backend and identity
#      provider per deployment without a rebuild — see src/config.ts and
#      src/auth/oidcConfig.ts. An EMPTY API_BASE_URL means "same origin" (use
#      the nginx /api/ proxy). The OIDC values are public identifiers (the
#      provider's issuer URL and a public client's id), not secrets.
set -eu

API_BASE_URL="${API_BASE_URL-http://localhost:8000}"
BACKEND_UPSTREAM="${BACKEND_UPSTREAM-http://backend:8000}"
OIDC_AUTHORITY="${OIDC_AUTHORITY-}"
OIDC_CLIENT_ID="${OIDC_CLIENT_ID-}"

# Both values are written into a JavaScript string / an nginx directive, so
# anything outside a plain URL is refused instead of escaped.
case "$API_BASE_URL" in
  *[!A-Za-z0-9:/._-]*)
    echo "API_BASE_URL contains characters that are not allowed: refusing to start" >&2
    exit 1
    ;;
esac
case "$OIDC_AUTHORITY" in
  ""|http://*|https://*) ;;
  *)
    echo "OIDC_AUTHORITY must be an http(s) URL (or empty): refusing to start" >&2
    exit 1
    ;;
esac
case "$OIDC_AUTHORITY$OIDC_CLIENT_ID" in
  *[!A-Za-z0-9:/._-]*)
    echo "OIDC_AUTHORITY / OIDC_CLIENT_ID contain characters that are not allowed: refusing to start" >&2
    exit 1
    ;;
esac
case "$BACKEND_UPSTREAM" in
  http://*|https://*) ;;
  *)
    echo "BACKEND_UPSTREAM must be an http(s) origin such as http://backend:8000" >&2
    exit 1
    ;;
esac
case "$BACKEND_UPSTREAM" in
  *[!A-Za-z0-9:/._-]*|*/|*//*/*|*://*/*)
    echo "BACKEND_UPSTREAM must be a bare origin (scheme, host, optional port): refusing to start" >&2
    exit 1
    ;;
esac

# Runs as the non-root nginx user. The build ships a placeholder config.js that
# this user does not own, so it cannot be overwritten in place; write a new file
# and rename it over the old one (that only needs write access to the directory,
# and readers never see a half-written file).
# (AEGIS_HTML_DIR exists only so the tests can write somewhere else.)
TARGET="${AEGIS_HTML_DIR:-/usr/share/nginx/html}/config.js"
cat > "${TARGET}.tmp" <<EOF
window.__AEGIS_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}", oidc: { authority: "${OIDC_AUTHORITY}", clientId: "${OIDC_CLIENT_ID}" } };
EOF
mv -f "${TARGET}.tmp" "$TARGET"
