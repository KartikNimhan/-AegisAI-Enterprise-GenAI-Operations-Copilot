"""Authentication: OIDC bearer-token verification and identity resolution.

The API is a resource server. `tokens.TokenVerifier` verifies an access token
against a published key set (`jwks.py`); `service.IdentityService` maps the
verified `(issuer, subject)` to an internal user, organization and role from
the database — never from token claims. FastAPI wiring lives in
`app.core.security`.
"""
