// Placeholder for local dev (npm run dev / vite preview). In the Docker
// image, docker-entrypoint.sh overwrites this file at container start
// from the API_BASE_URL environment variable. Left empty here:
// src/config.ts falls back to VITE_API_BASE_URL or the localhost default.
window.__AEGIS_CONFIG__ = window.__AEGIS_CONFIG__ || {};
