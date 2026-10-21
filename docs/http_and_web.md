# Browser app and optional HTTP MCP

Both interfaces are included in 0.2.0. Nothing is hosted or deployed automatically. The default MCP entry point still uses stdio and requires no network listener or credentials.

## Local browser application

```sh
make build
make venv
.venv/bin/dreamseed-web --port 8765
```

Open `http://127.0.0.1:8765`. The app supports bounded searches, progress monitoring, cancellation, inspection, comparison, official verification, biome maps, and generated terrain previews. Requests are explicit editable JSON with the same validated schemas as MCP. There is no natural language model in the browser app.

Seed cards can populate inspection, terrain, and exact verification requests. Exact verification preserves the preceding search criteria. Terrain output includes a heightmap, a draggable surface preview, and an OBJ download. Read the separate validation status and caveats before teleporting.

The listener binds only to loopback. Host and Origin headers are checked. Every API call requires a per process unpredictable session token that the local page supplies in a header. Responses disable caching, external scripts, framing, object embedding, and unrestricted connections through a content security policy. Assets use fixed routes, request bodies are capped at 1 MiB, and connection handling is limited to eight workers. No arbitrary filesystem path or console command is accepted.

This is for one trusted machine owner. It does not defend against malicious software already running as that owner. Do not expose or proxy the browser app to a public network.

By default the browser uses `web-jobs`, HTTP MCP uses `http-jobs`, and stdio uses `jobs` under the platform's DreamSeed state directory. `DREAMSEED_STATE_DIR` can override a store explicitly; do not point two running processes at the same directory. Standalone terrain exports use temporary job state and never recover or rewrite the stdio store.

## Authenticated MCP resource server

```sh
make venv
.venv/bin/python -m pip install -e '.[http]'
.venv/bin/dreamseed-http --port 8766
```

Configure these trusted operator environment settings before starting:

| Setting | Meaning |
| --- | --- |
| `DREAMSEED_HTTP_ISSUER` | Your OAuth authorization server's exact HTTPS issuer |
| `DREAMSEED_HTTP_RESOURCE` | This MCP resource's HTTPS URL ending in `/mcp` |
| `DREAMSEED_HTTP_SUBJECT` | The one permitted owner subject |
| `DREAMSEED_HTTP_PUBLIC_KEY` | PEM public verification key, never a private signing key |
| `DREAMSEED_HTTP_ALGORITHM` | EdDSA, RS256, or ES256; default EdDSA |

Missing or unsafe configuration stops startup. The server does not issue tokens or implement a login screen. An external OAuth authorization server must issue signed access tokens with the correct `iss`, `aud`, `sub`, `client_id` or `azp`, `iat`, `exp`, and `scope` containing `dreamseed:use`. Wrong audience, issuer, subject, scope, signature, expiry, or algorithm is rejected. Symmetric secrets, unsigned JWTs, token forwarding, and arbitrary remote key URLs are not accepted.

The official MCP SDK serves protected resource metadata and authentication challenges. The implementation follows the MCP [resource server authorization model](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization). Tests use freshly generated signing keys only in memory, with actual authenticated HTTP tool calls against the native engine.

The listener still binds to `127.0.0.1`. Public operation requires a separately configured trusted TLS proxy and an OAuth provider. Forward only the intended hostname and strip untrusted proxy headers. The application accepts explicit hosts and origins, limits body size and simultaneous requests, and disables access logging. It does not implement public account registration, billing, independent user job isolation, or a managed hosting service.

All accepted tokens must represent the same configured owner, whose clients share the retained job store. This is intentional single owner authorization, not a multiuser service. Do not remove that restriction without adding per user storage and resource accounting. Deployment, identity provider selection, DNS, and production security review remain operator tasks and are not performed by the build.
