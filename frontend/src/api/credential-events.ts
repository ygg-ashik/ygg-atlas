// The `credential_events.event` values the credential API records (backend
// app/identity/api_tokens.py). Review cards name the event a write will log;
// kept free of HTTP imports so any view can use them.
export const CREDENTIAL_EVENT = {
  tokenCreated: 'token.created',
  tokenRevoked: 'token.revoked',
  tokensRevokedAll: 'tokens.revoked_all',
  clientRegistered: 'client.registered',
  clientRevoked: 'client.revoked',
  familyRevoked: 'oauth.family_revoked',
} as const;
