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

# Security headers (AIGSEC-011). The Content-Security-Policy allows scripts, styles, images and
# fonts from this origin only (no inline code, no eval), and network connections and frames only
# to this origin plus the two origins the app is configured to talk to: the API (when it is not
# same-origin) and the sign-in provider (token requests, and the silent-renew frame). Both come
# from the values validated above, so the policy can never be wider than the configuration.
# HSTS is opt-in (HSTS_MAX_AGE, in seconds): send it only when this site is served over HTTPS
# by whatever terminates TLS in front of it; it never includes includeSubDomains or preload.
origin_of() {
  printf '%s\n' "$1" | sed -n 's#^\(https\{0,1\}://[^/]*\).*#\1#p'
}
API_ORIGIN="$(origin_of "$API_BASE_URL")"
OIDC_ORIGIN="$(origin_of "$OIDC_AUTHORITY")"
CONNECT_SRC="'self'"
FRAME_SRC="'self'"
if [ -n "$API_ORIGIN" ]; then
  CONNECT_SRC="$CONNECT_SRC $API_ORIGIN"
fi
if [ -n "$OIDC_ORIGIN" ]; then
  CONNECT_SRC="$CONNECT_SRC $OIDC_ORIGIN"
  FRAME_SRC="$FRAME_SRC $OIDC_ORIGIN"
fi
CSP="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src ${CONNECT_SRC}; frame-src ${FRAME_SRC}; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"

HSTS_MAX_AGE="${HSTS_MAX_AGE-}"
case "$HSTS_MAX_AGE" in
  "") HSTS="" ;;
  *[!0-9]*)
    echo "HSTS_MAX_AGE must be a whole number of seconds (or empty): refusing to start" >&2
    exit 1
    ;;
  *) HSTS="max-age=${HSTS_MAX_AGE}" ;;
esac
if [ "$HSTS" = "max-age=0" ]; then
  HSTS=""
fi

# Included by nginx at http level (conf.d/*.conf); the server block sends $aegis_csp and
# $aegis_hsts. An empty value makes nginx omit the header.
CONF_DIR="${AEGIS_NGINX_CONF_DIR:-/etc/nginx/conf.d}"
HEADERS="${CONF_DIR}/aegis-security-headers.conf"
{
  printf 'map $host $aegis_csp {\n    default "%s";\n}\n' "$CSP"
  printf 'map $host $aegis_hsts {\n    default "%s";\n}\n' "$HSTS"
} > "${HEADERS}.tmp"
mv -f "${HEADERS}.tmp" "$HEADERS"
