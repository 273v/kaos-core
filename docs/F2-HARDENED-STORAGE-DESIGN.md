# F2 — Hardened credential & session storage

> Design for an **optional** layered credential / session storage
> system in kaos-core. Builds on the existing `CredentialStore`,
> `OAuthToken`, `resolve_secret`, and `ProfileManager` surfaces; keeps
> the base install dependency-light by gating every hardening tier
> behind opt-in extras.
>
> Research grounding: a 2026 audit of how `gh`, AWS CLI, gcloud, Azure
> CLI / MSAL, Hugging Face, OpenAI Codex, 1Password, Doppler, and
> Anthropic's Claude Code actually store credentials. **No tool in
> the field treats keyring as required.** Every shipped system has a
> file-based fallback. We design for the same reality.

## 1. Goals

- **Optional hardening, not mandatory.** Base `kaos-core` install
  must continue to work with no new dependencies. Today's plaintext
  `CredentialStore` (post-F1: `chmod 0o600` on POSIX, NTFS DACL on
  Windows) becomes the *fallback floor*, not the default ceiling.
- **Cross-platform parity by capability.** macOS Keychain, Windows
  Credential Manager (DPAPI/WinVault), Linux Secret Service
  (libsecret), KDE Wallet — via the `keyring` package. When `keyring`
  is unavailable (headless Linux / WSL / Docker), an **encrypted
  file** with `Fernet` + `Argon2id` is the next tier — strictly
  better than plaintext-with-0600 against the *real* leak vector
  (config files getting sync'd to Dropbox / Time Machine / a dotfile
  repo).
- **OAuth-first credential acquisition.** Provider integrations
  (Anthropic, OpenAI, Google, GitHub, generic OIDC) acquire tokens
  via OAuth 2.1 — PKCE+loopback for desktop, RFC 8628 device flow
  for headless / SSH / WSL. Refresh-token rotation default-on.
- **Composable with the existing settings chain.** `resolve_secret`
  stays the public entry point. The new tiers slot *between* env-var
  resolution and the existing plaintext store, transparent to
  callers.
- **Profile-aware.** Credentials and sessions are scoped per profile
  (today's `ProfileManager`). Migrating between profiles must not
  cross-contaminate stored secrets.
- **Auditable.** Every read / write / migration emits a structured
  log line via `kaos_core.logging.get_logger`. No secret values in
  logs (existing `SecretStr` redaction conventions).

## 2. Non-goals (v1)

- **DPoP / mTLS sender-constrained tokens.** Design the API so a
  proof-of-possession key can be added later without breaking the
  token shape; do not ship the implementation.
- **Browser cookie/keychain bridges** (Chrome's keystore, Firefox's
  `key4.db`, etc.).
- **Custom DPAPI integration** outside what `keyring` already
  provides on Windows.
- **Full SSO broker integration** (Microsoft WAM, macOS PRT). MSAL
  has its own toolkit for this; users who need it install the
  provider-specific package alongside.
- **Roaming-profile-safe credentials.** DPAPI breaks under roaming;
  document this and recommend `%LOCALAPPDATA%` rather than design a
  new envelope format around it.

## 3. Storage hierarchy

### 3.1 Read order (first hit wins)

```
1. Settings field (pydantic SecretStr from env via pydantic-settings)
2. Direct environment variable                                 (KAOS_*_API_KEY)
3. OS keyring                                                  (kaos-core[keyring])
   - service: "kaos-core/{profile}/{module}"
   - username: "{service_name}/{key}"
4. Encrypted file at $XDG_STATE_HOME/kaos/credentials.enc      (kaos-core[encrypted-store])
   - Fernet (AES-128-CBC + HMAC-SHA-256)
   - KEK derived via Argon2id from a per-profile passphrase
   - Passphrase source: keyring-stashed → env → interactive prompt
5. Plaintext JSON at $XDG_STATE_HOME/kaos/credentials.json     (today's CredentialStore)
   - Mode 0600 / NTFS DACL
   - Loud warning on every load: "running with plaintext credentials"
6. Not found → resolve_secret returns None
```

### 3.2 Write order

The reverse: write to the **strongest available tier**, then *delete*
the secret from any weaker tier where it previously lived. This
prevents stale plaintext lingering after a user upgrades.

### 3.3 Probe order at startup

Layered backend selection happens once per `KaosContext` lifecycle:

1. `keyring.get_keyring()` — accept only if `backend.priority >= 1`
   AND `backend.__module__` is not `keyrings.alt.*`. (Alt backends
   silently store plaintext under `~/.local/share/python_keyring/`;
   pulling them in transitively makes "keyring success" a lie.)
2. If keyring rejected, probe the encrypted-file tier — exists if
   `cryptography>=44` is importable AND `$XDG_STATE_HOME/kaos/credentials.enc`
   exists OR `KAOS_PASSPHRASE` is set.
3. Fall through to plaintext.

Probe results are cached on the `KaosRuntime`; the per-call read path
just dispatches to the elected backend.

### 3.4 Headless / WSL detection

Skip the keyring probe entirely (it's slow and hangs on first-touch
prompts) when:

- Linux AND `os.environ.get("DISPLAY")` is empty
- AND `os.environ.get("WAYLAND_DISPLAY")` is empty
- AND not `sys.stdout.isatty()`
- OR `/proc/version` contains `microsoft` (WSL marker) AND
  `KAOS_WSL_USE_KEYRING=1` is not set

Users can force the probe with `KAOS_FORCE_KEYRING=1`.

## 4. Module layout

All new code lives under `kaos_core/config/storage/` — a new
sub-package that holds the tier implementations and the dispatcher.
`CredentialStore` stays where it is (it's tier 5).

```
kaos_core/config/
├── credentials.py            # tier 5 (existing) — plaintext + NTFS DACL
├── auth.py                   # OAuthToken (existing) — extended with refresh helpers
├── secrets.py                # resolve_secret (existing) — extended chain
├── settings.py               # KaosSettings (existing) — new fields below
├── profiles.py               # ProfileManager (existing) — per-profile keyring scoping
└── storage/                  # NEW
    ├── __init__.py
    ├── base.py               # SecretStorage Protocol + StorageProbe + StorageTier enum
    ├── keyring_backend.py    # tier 3 — kaos-core[keyring]
    ├── encrypted_file.py     # tier 4 — kaos-core[encrypted-store]
    ├── envelope.py           # Fernet + Argon2id envelope (versioned JSON)
    ├── dispatcher.py         # tier-aware reader/writer with auto-migration
    └── xdg.py                # XDG basedir resolver (POSIX) / KnownFolder (Windows)

kaos_core/auth/               # NEW
├── __init__.py
├── flows.py                  # AuthFlow Protocol + flow runners
├── pkce_loopback.py          # RFC 8252 §7.3 — desktop with browser
├── device_flow.py            # RFC 8628 — headless / SSH / WSL
└── refresh.py                # refresh-token rotation + revocation
```

## 5. Public surfaces

### 5.1 `SecretStorage` Protocol (`config/storage/base.py`)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SecretStorage(Protocol):
    """Read/write/delete a secret keyed by (module, service, key).

    Implementations: KeyringStorage, EncryptedFileStorage,
    PlaintextStorage (today's CredentialStore wrapped to fit).
    """
    tier: "StorageTier"

    def get(self, module: str, service: str, key: str = "default") -> str | None: ...
    def set(self, module: str, service: str, key: str, value: str) -> None: ...
    def delete(self, module: str, service: str, key: str = "default") -> None: ...
    def list_services(self, module: str) -> list[str]: ...
    def is_available(self) -> bool: ...
```

### 5.2 `StorageTier` enum

```python
class StorageTier(IntEnum):
    """Stronger storage gets the higher number; defaults to highest available."""
    NONE = 0           # not found / unavailable
    PLAINTEXT = 10     # CredentialStore (current)
    ENCRYPTED_FILE = 20  # Fernet + Argon2id KEK
    KEYRING = 30       # OS-native (macOS / DPAPI / libsecret / KWallet)
    SYSTEM_BROKER = 40  # reserved for v2 (WAM, macOS PRT)
```

### 5.3 Tier dispatcher (`config/storage/dispatcher.py`)

```python
class HardenedCredentialStore:
    """Tier-aware credential store. Drop-in replacement for
    CredentialStore at the resolve_secret call site.

    Probes available backends on first use; reads from the strongest
    backend that has the secret; writes to the strongest available;
    auto-migrates secrets up the tier list on read.
    """

    def __init__(
        self,
        *,
        profile: str = "default",
        prefer_tier: StorageTier | None = None,  # cap (testing / debugging)
        fallback: SecretStorage | None = None,   # injection point for tests
    ) -> None: ...

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        """Read in tier order. Auto-migrate to the strongest available
        tier on hit (so subsequent reads are faster + the secret
        moves out of weaker storage)."""

    def set(self, module: str, service: str, key: str, value: str) -> None:
        """Write to strongest available tier; delete from all weaker
        tiers to prevent stale plaintext lingering."""

    @property
    def active_tier(self) -> StorageTier: ...

    def migrate(self, module: str, *, dry_run: bool = False) -> dict[str, StorageTier]: ...
```

### 5.4 OAuth flow surface (`kaos_core.auth`)

```python
class AuthFlow(Protocol):
    """Provider-agnostic OAuth flow runner.

    Concrete impls: PKCELoopbackFlow, DeviceCodeFlow.
    """
    async def run(
        self,
        *,
        client_id: str,
        scopes: Sequence[str],
        authorization_endpoint: str,
        token_endpoint: str,
        device_authorization_endpoint: str | None = None,
    ) -> OAuthToken: ...


@dataclass
class FlowSelector:
    """Choose between PKCE+loopback and device-flow at runtime.

    Default heuristic: if a browser is available (DISPLAY /
    WAYLAND_DISPLAY / sys.platform in {'darwin','win32'}) AND we
    can bind to 127.0.0.1 → PKCE+loopback. Otherwise → device flow.
    """
    force_device: bool = False
    force_loopback: bool = False
    loopback_port_range: tuple[int, int] = (49152, 65535)

    def pick(self) -> AuthFlow: ...
```

### 5.5 Extended `OAuthToken`

Today's `OAuthToken` already has `access_token`, `refresh_token`,
`expires_at`, `scope`. Add three things:

```python
class OAuthToken(KaosModel):
    # existing fields...
    issuer: str | None = None         # NEW: token endpoint URL — required for refresh
    client_id: str | None = None      # NEW: required for refresh
    obtained_at: str | None = None    # NEW: ISO timestamp — debugging / audit

    async def refresh(self, *, client: httpx.AsyncClient | None = None) -> OAuthToken:
        """Return a new token by calling the issuer's token endpoint
        with grant_type=refresh_token. Rotates the refresh_token if
        the issuer returns a new one (OAuth 2.1 SHOULD)."""
```

The new fields are nullable so existing serialized tokens still load.

### 5.6 Updated `resolve_secret` chain

```python
def resolve_secret(
    settings_value: SecretStr | None = None,
    *,
    env_var: str | None = None,
    credential_store: HardenedCredentialStore | CredentialStore | None = None,
    module: str = "",
    service: str = "",
    key: str = "default",
) -> str | None:
    # 1. settings (pydantic SecretStr)
    if settings_value is not None:
        return settings_value.get_secret_value()

    # 2. env var
    if env_var is not None:
        if (value := os.environ.get(env_var)):
            return value

    # 3. credential_store — HardenedCredentialStore handles the tier
    #    chain internally; passing a legacy CredentialStore still
    #    works (= tier 5 only).
    if credential_store is not None and module and service:
        return credential_store.get(module, service, key)

    return None
```

Backward-compatible: any caller passing a plain `CredentialStore`
keeps working.

## 6. Encrypted-file envelope (`config/storage/envelope.py`)

Versioned JSON envelope so we can rotate the KDF or cipher without
breaking older files.

```json
{
  "version": 1,
  "kdf": {
    "algorithm": "argon2id",
    "salt": "<base64 16 bytes>",
    "memory_cost_kib": 65536,
    "iterations": 3,
    "lanes": 4
  },
  "cipher": "fernet",
  "ciphertext": "<urlsafe-b64 Fernet token>",
  "created_at": "2026-05-10T17:30:00Z",
  "rotated_at": null
}
```

KDF parameters follow OWASP 2026 desktop-interactive guidance: 64 MiB
memory, 3 iterations, 4 lanes. The CLI emits a warning if the box
can't sustain those (e.g., a constrained CI runner) and offers to
write with reduced params; the envelope's KDF block records what was
actually used.

### 6.1 KEK source priority

```
1. $KAOS_PASSPHRASE                    (CI / scripted)
2. Keyring entry "kaos-core/{profile}/kek"   (set once, retrieved silently)
3. Interactive `getpass()` prompt      (TTY only)
4. Refuse — encrypted store unusable, fall through to plaintext
```

The "KEK in keyring" pattern is `gh`'s trick: keyring becomes the
*key-encryption-key* store, the file holds the data, and accidental
backup of the file alone is useless.

### 6.2 Threat model summary

| Threat | Plaintext 0600 | Encrypted file (passphrase) | Encrypted file (KEK in keyring) | Keyring native |
|---|---|---|---|---|
| Other local users | ✓ | ✓ | ✓ | ✓ |
| Backup/sync leak | ✗ | ✓ | ✓ | ✓ |
| Stolen unencrypted disk | ✗ | ✓ | ✗ | ✗ (keychain on same disk) |
| Same-user malware | ✗ | partial | ✗ | partial |

Encrypted-file with KEK-in-keyring = roughly keyring-equivalent for
steady state, *strictly better* than plaintext-0600 against backup
leakage.

## 7. XDG path discipline (`config/storage/xdg.py`)

Tokens are runtime state, NOT user config. Use `$XDG_STATE_HOME` (=
`~/.local/state` default), not `$XDG_CONFIG_HOME`. Users routinely
sync `~/.config` into dotfile repos; rarely sync `~/.local/state`.

| Path | Purpose | Default | Mode |
|---|---|---|---|
| `$XDG_CONFIG_HOME/kaos/config.toml` | non-secret config (model, region) | `~/.config/kaos/config.toml` | 0644 |
| `$XDG_STATE_HOME/kaos/credentials.enc` | encrypted refresh tokens / API keys | `~/.local/state/kaos/credentials.enc` | 0600 |
| `$XDG_STATE_HOME/kaos/credentials.json` | plaintext fallback | same dir | 0600 / NTFS DACL |
| `$XDG_STATE_HOME/kaos/oauth/{provider}.meta.json` | issuer URL, client_id, scopes (NOT tokens) | same | 0644 |
| `$XDG_CACHE_HOME/kaos/sessions/` | per-session ephemeral | `~/.cache/kaos/sessions/` | 0700 dir |

**Windows**: `%LOCALAPPDATA%\kaos\` — never `%APPDATA%`. DPAPI breaks
under roaming profiles; using `LOCALAPPDATA` keeps the credential
store machine-bound. NTFS DACL via the F1.5 `_harden_owner_only`
helper.

**macOS**: keyring service `kaos-core` (Keychain). Non-secret state
in `~/Library/Application Support/kaos/`.

`xdg.py` exports:
```python
def kaos_config_dir() -> Path: ...  # config
def kaos_state_dir() -> Path: ...   # secrets + tokens
def kaos_cache_dir() -> Path: ...   # ephemeral
```

`KAOS_CONFIG_DIR` / `KAOS_STATE_DIR` / `KAOS_CACHE_DIR` env overrides
for testing and containerization.

## 8. Settings additions (`config/settings.py`)

```python
class KaosSettings(BaseSettings):
    # ... existing fields ...

    # NEW — credential storage
    credential_storage_tier: StorageTier | None = Field(
        default=None,
        description="Cap the storage tier (mostly for testing). None = use strongest available.",
    )
    credential_storage_disable_keyring: bool = False  # KAOS_DISABLE_KEYRING
    credential_storage_force_plaintext: bool = False  # KAOS_FORCE_PLAINTEXT_CREDS

    # NEW — passphrase source for encrypted store
    credential_passphrase: SecretStr | None = None  # KAOS_PASSPHRASE
```

Profile path resolution moves from `Path(".kaos-credentials.json")`
to `kaos_state_dir() / "credentials.{enc|json}"` based on tier.

## 9. OAuth flows

### 9.1 PKCE + loopback (`auth/pkce_loopback.py`)

Standard RFC 8252 §7.3 implementation:

1. Generate `code_verifier` (43–128 random URL-safe chars).
2. Bind to a random ephemeral port on `127.0.0.1`. Range
   `[49152, 65535]` (IANA dynamic). Refuse anything outside.
3. Build authorization URL with `code_challenge=S256(verifier)` and
   `redirect_uri=http://127.0.0.1:{port}/callback`.
4. Open browser via `webbrowser.open()`. Bail to device flow if it
   fails (via `FlowSelector`, not internally).
5. Tiny `aiohttp` (or stdlib `http.server`) handler waits for the
   callback, validates `state`, exchanges `code` for tokens at
   `token_endpoint`.
6. Returns `OAuthToken` with `issuer` and `client_id` populated for
   refresh.

### 9.2 Device flow (`auth/device_flow.py`)

Standard RFC 8628:

1. POST to `device_authorization_endpoint` → receive
   `(device_code, user_code, verification_uri, interval)`.
2. Display `user_code` + `verification_uri_complete` (or pair) to
   user via stdout (and `qrcode` if extra is installed — optional
   `kaos-core[oauth-qr]`).
3. Poll `token_endpoint` every `interval` seconds (with exponential
   backoff on `slow_down`).
4. Stop when token returned or after `expires_in` seconds.

### 9.3 Refresh (`auth/refresh.py`)

```python
async def refresh_token(
    token: OAuthToken,
    *,
    client: httpx.AsyncClient | None = None,
) -> OAuthToken:
    """POST grant_type=refresh_token to token.issuer with
    refresh_token. Returns a new OAuthToken (rotated refresh per
    OAuth 2.1)."""
```

Auto-refresh hook in `OAuthToken.is_expired_within(seconds: int)` —
default 30s window — so callers refresh proactively rather than on
401.

### 9.4 Library choice

**Authlib** (BSD-3-Clause, healthy maintenance, supports both `httpx`
async and `requests` sync). Authlib's `OAuth2Client` handles PKCE
challenge generation, state, and token exchange; we only need to
write the loopback HTTP server and device-code polling loop.

`oauthlib`/`requests-oauthlib` is an alternative but is sync-only and
slower-moving. We're async-first.

`msal` is locked to Microsoft Entra; not general-purpose. `google-auth`
locked to Google. Our integrations cross multiple IdPs so we want
generic.

## 10. Optional extras

```toml
[project.optional-dependencies]
keyring = [
  "keyring>=25.7",
  # SecretStorage and jeepney are pure-Python, no compilers needed
  # on Linux. Marker scopes them so macOS/Windows installs stay
  # lean.
  "SecretStorage>=3.4 ; sys_platform == 'linux'",
  "jeepney>=0.9 ; sys_platform == 'linux'",
]
encrypted-store = [
  "cryptography>=44",   # Fernet + Argon2id (44+ adds Argon2id)
]
oauth = [
  "authlib>=1.7",
  "httpx>=0.28",        # likely already pulled in elsewhere
]
oauth-qr = [
  "qrcode[pil]>=7",     # device-flow: display QR for verification_uri_complete
]
hardened = [             # umbrella — pulls all four
  "kaos-core[keyring,encrypted-store,oauth]",
]
windows-secure = [       # F1.5 (already shipped) — kept here for completeness
  "pywin32>=308 ; sys_platform == 'win32'",
]
```

Base install adds zero new transitive deps. Users opt in:

```bash
uv pip install kaos-core[hardened]
```

## 11. Migration path from today's `CredentialStore`

The existing `~/.kaos-credentials.json` (mode 0600) becomes Tier 5 of
the dispatcher. On first start with the hardened path enabled:

1. Detect legacy file at the working directory, `~/.kaos-credentials.json`,
   or anywhere user-configured.
2. If `keyring` or `encrypted-store` extras are available, prompt
   (TTY only) or auto-migrate (`KAOS_AUTO_MIGRATE_CREDS=1`) every
   secret upward.
3. After successful migration, delete the legacy file. Audit-log the
   migration with hashes (not values) of each migrated key.
4. If running non-interactively without `KAOS_AUTO_MIGRATE_CREDS`,
   warn loudly on every load: "kaos: credentials are stored in
   plaintext at $PATH; run `kaos-core creds migrate` to upgrade".

CLI verbs (`kaos-core` adds a `creds` subcommand):

```
kaos-core creds list                # show stored services per tier
kaos-core creds set <module> <service> [<key>]   # interactive
kaos-core creds migrate [--dry-run] # walk upward through tiers
kaos-core creds rotate <module>     # re-encrypt with new KEK
kaos-core creds purge --tier=plaintext
kaos-core auth login <provider>     # OAuth flow runner
kaos-core auth refresh <provider>   # forced refresh
kaos-core auth status               # token expiry / scope summary
```

## 12. Phased rollout

| Phase | Ship | Skip |
|---|---|---|
| **F2.1** — Tier infrastructure | `SecretStorage` Protocol, `StorageTier` enum, `HardenedCredentialStore` dispatcher, `kaos_state_dir()` / `kaos_config_dir()`. Tier 1 (env) and Tier 5 (plaintext) wired through. | All other tiers, OAuth |
| **F2.2** — keyring tier | `KeyringStorage` (Tier 3), probe + headless detection, `kaos-core[keyring]` extra, dispatcher integration | encrypted-file, OAuth |
| **F2.3** — encrypted-file tier | `EncryptedFileStorage` (Tier 4), envelope module, KEK source chain, `kaos-core[encrypted-store]` extra | OAuth |
| **F2.4** — OAuth flows | `auth/flows.py`, `pkce_loopback.py`, `device_flow.py`, `OAuthToken.refresh`, `kaos-core[oauth]` extra | DPoP, broker integrations |
| **F2.5** — CLI verbs + migration | `kaos-core creds` and `kaos-core auth` subcommands, auto-migration on first load | — |
| **F2.6** (deferred) — DPoP keys, WAM/PRT brokers, browser-cookie bridges | — | — |

Each phase ships independently with its own tests; F2.1 lays the
foundation, F2.5 closes the user-facing loop.

## 13. Test strategy

### 13.1 Unit (per-tier)

- **PlaintextStorage**: existing `test_credentials.py` (post-F1)
  covers this tier today.
- **KeyringStorage**: monkey-patch `keyring.set_password` /
  `get_password` with an in-memory dict; assert the tier-3 path
  reads/writes via `keyring`. Probe-failure path: simulate
  `NoKeyringError`. Headless detection: monkey-patch `os.environ`
  and `sys.stdout.isatty`.
- **EncryptedFileStorage**: round-trip a secret through the envelope
  in a tmp dir; verify file mode is 0600 / NTFS DACL applied (reuse
  the F1.5 helper); assert KDF params recorded match what was used;
  test `KAOS_PASSPHRASE` env path AND keyring-stashed-KEK path.
- **Dispatcher**: a tier-stack test using three in-memory
  implementations of `SecretStorage` with controlled `is_available()`
  responses; assert read-from-strongest, write-to-strongest, and
  delete-from-weaker invariants.

### 13.2 Integration

- **Migration**: write to plaintext, enable encrypted tier, read →
  observe value migrates to encrypted; legacy file removed; structured
  log line emitted.
- **Profile isolation**: two profiles, same `(module, service, key)`,
  different values; assert no cross-read.
- **OAuth flow**: spin up a tiny test IdP via `aiohttp` test server
  (we already use this pattern in kaos-web); run PKCE+loopback end-
  to-end; assert refresh-token rotation.
- **Device flow**: same test IdP exposing a device-authorization
  endpoint; assert polling cadence + `slow_down` handling.

### 13.3 Cross-OS

The new tiers run on the existing macOS-arm64 and Windows-x64 matrix
legs (now passing post-F1). Specific to verify:

- macOS Keychain: keyring-tier write+read works in CI (CI runners
  *do* have a Keychain); document behavior on `security unlock-keychain`.
- Windows: keyring-tier writes hit DPAPI / WinVault. CI runners
  expose `Windows Credentials` programmatically.
- Linux self-hosted runner: explicitly headless; assert keyring tier
  is bypassed; encrypted-file tier picks up `KAOS_PASSPHRASE` from
  env without prompting.

## 14. Risks + mitigations

- **Risk**: keyring prompts hang in CI. **Mitigation**: headless
  detection + `KAOS_DISABLE_KEYRING=1` opt-out + probe-with-timeout.
- **Risk**: `cryptography>=44` adds compile cost on platforms without
  wheels. **Mitigation**: 3.13/3.14 wheels exist for every Tier 1
  platform; we only fall to source-build on 3.15-alpha (where we're
  already source-building rpds-py / pydantic-core).
- **Risk**: users ship `~/.kaos/` to a dotfile repo and leak secrets.
  **Mitigation**: secrets live in `$XDG_STATE_HOME` (= `~/.local/state`)
  not `$XDG_CONFIG_HOME` (= `~/.config`). Document explicitly. Add a
  `kaos-core creds gitignore-check` verb that warns if any secret
  path is inside a tracked git tree.
- **Risk**: `keyrings.alt` slips in transitively and silently writes
  plaintext under `~/.local/share/python_keyring/`. **Mitigation**:
  refuse `backend.__module__.startswith("keyrings.alt")` in the
  probe.
- **Risk**: refresh-token rotation breaks long-running daemons (the
  *previous* refresh token is invalidated server-side after rotation).
  **Mitigation**: in-process atomic update of stored token via
  `os.replace` after the new tokens are persisted; document
  multi-process daemon pattern (use a single coordinator).

## 15. Open questions for review

1. **Default tier** when all extras installed — strongest available
   (= keyring), or strongest with explicit user opt-in (= file with
   warn-and-offer-to-upgrade)? My recommendation: strongest available
   by default; users override via settings.
2. **Multi-account / multi-tenant**: `(profile, module, service, key)`
   four-tuple is what we have. Should the OAuth flows include an
   explicit `account_hint` (e.g., for Google Workspace organisation)?
   I'd defer to F2.4 design.
3. **Should the CLI verbs live in kaos-core directly or in a new
   `kaos-cli` package?** Today's `kaos-core` CLI is small; adding
   `creds` + `auth` subcommands roughly doubles its surface. Either
   is defensible.
4. **Bring `argon2-cffi` directly or use `cryptography`'s Argon2id?**
   `cryptography>=44` includes it natively → one fewer dep. Going
   with `cryptography`-native unless someone benchmarks it as
   significantly slower than `argon2-cffi`.
5. **Where do we draw the line on provider integrations shipping in
   kaos-core vs in `kaos-llm` / `kaos-web`?** OAuth flow *runners*
   are generic and belong here; provider-specific *clients*
   (Anthropic OAuth, GitHub OAuth) belong in their own packages. v1
   ships only the runners + the `OAuthToken` type.

## 16. Out of scope (future work)

- DPoP / mTLS sender-constrained tokens (RFC 9449)
- Microsoft WAM / Apple PRT broker integrations
- Browser keystore bridges (Chrome `Login Data`, Firefox `key4.db`)
- Hardware-key-backed credentials (TPM, YubiKey, Apple Secure Enclave)
- Roaming-profile-safe envelopes for Windows DPAPI
- A daemon process to keep tokens warm in memory across CLI invocations
- Audit-log persistence beyond structured logging (e.g., signed
  audit trail for compliance use cases)
