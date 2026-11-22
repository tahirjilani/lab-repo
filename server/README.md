# DemoWallet lab server

The server half of the talk's thesis: **the client collects signals, the server decides.**
FastAPI, in-memory state, one lab account (`acc-001`, €2,450.00), reset on restart.

```bash
# from the repo root
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt          # Windows: .venv\Scripts\Activate.ps1 instead of source …
pytest server
uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Real Play Integrity tokens (`DW_VERDICT_MODE=google`) also need `pip install -r server/requirements-google.txt`; the lab doesn't.

The app talks to it by default (`demowallet.apiBaseUrl=http://10.0.2.2:8000`; the emulator's 10.0.2.2 is your Mac's localhost).
Full setup: [`docs/setup.md`](../docs/setup.md).

## What `POST /api/transfers` does

1. Rebuilds the canonical transfer `v1|account|payeeId|amountCents|currency|nonce|actor` and hashes it (SHA-256, hex).
2. **Integrity layer** (`verify.py`): decodes the Play Integrity token and **blocks** if `requestPackageName` isn't `com.demo.wallet` or `requestHash` doesn't match the recomputed hash. Stale timestamp, unrecognized app, missing device label, unknown app controlling the device → step-up. No token at all → step-up, never a silent pass.
3. **RASP layer** (`rasp.py`): flags from the body and the `X-RASP` header (disagreement is itself a signal).
4. **Agent layer** (`agent_tokens.py`): the assistant must present a scoped, short-lived **agent token** in `X-Agent-Token`.
5. **Risk engine** (`risk.py`): score = sum over layers of each layer's worst signal (0–100); bands `<25 allow · <50 monitor · <90 step_up · ≥90 block`; a signal can also force a minimum decision (its *floor*).
6. Context rules always apply: replayed nonce, wrong account, unknown payee, insufficient funds → block; user transfers over €1,000 → step-up.

The response adds `riskScore`, `signals` and `requestHash` to the app's contract (the app ignores them; they're for curl and the stage). Each decision is also logged on the console.

## Agent tokens

The user (never the agent) delegates one action:

```bash
curl -s localhost:8000/api/agent-tokens -H "Authorization: Bearer $SESSION" -H 'X-Actor: user' \
  -H 'Content-Type: application/json' \
  -d '{"agentId":"demowallet-assistant/1.0","action":"transfer","maxAmountCents":5000,"payeeId":"ana","ttlSeconds":300}'
```

`dwat1.<claims>.<HMAC-SHA256>` with `account, agent_id, action, max_amount_cents, currency, payee_id?, iat, exp`. Max amount is capped by the agent limit (deck slide 18, `DW_AGENT_LIMIT_CENTS`, default €100), TTL by `DW_AGENT_TOKEN_MAX_TTL_SECONDS` (600). **Single use**: a token is burned the first time it's presented with a valid signature, in scope or not, even if that transfer is blocked, so a €100 grant shown on a €200 transfer can't be replayed for €100 later. Out of scope (amount, payee, action, agent id) or expired → step-up; forged or another account's token → block. The app asks you to **Allow** before the assistant acts, mints the token with `X-Actor: user` (payee-scoped, `min(amount, agent limit)`, 300 s), shows it in the chat, then sends it as `X-Agent-Token`. Denying sends nothing. "Send €200 to Ana" gets a €100 token and is out of scope: step-up (55) with `device_ok`, block (90) with the default `emulator` profile, where the out-of-scope points land on top of the failed verdict.

## Mock verdict mode (default) — no Google Cloud needed

`DW_VERDICT_MODE=mock`. When the app sends no token (it sends `integrity.error = NOT_CONFIGURED` with `cloudProjectNumber=0`), the server simulates the verdict Google would return, **bound to the hash the device computed** (`clientRequestHash`), so a body altered in transit still fails the hash check. Profiles (`DW_MOCK_VERDICT`, or switch live):

| profile | simulates |
|---|---|
| `emulator` (default) | sideloaded app on an emulator: no device label, `UNRECOGNIZED_VERSION`, `UNLICENSED` |
| `device_ok` | Play-installed app, certified locked device |
| `basic` | rooted-but-passing phone: `MEETS_BASIC_INTEGRITY` only |
| `controlled` | `device_ok` + `appAccessRiskVerdict: UNKNOWN_CONTROLLING` (an accessibility agent) |
| `none` | no verdict → "missing" |

```bash
curl -s localhost:8000/api/lab/mock-verdict -H 'Content-Type: application/json' -d '{"profile":"device_ok"}'
curl -s localhost:8000/api/lab/status
curl -s localhost:8000/api/lab/decisions | python3 -m json.tool
python -m server.mock_token --profile device_ok --canonical "v1|acc-001|ana|100|EUR|00ff|user"   # explicit token
```

If the body has no well-formed `clientRequestHash` (64 lowercase hex), there's nothing to bind a simulated verdict to: it counts as a missing verdict (step-up). Otherwise a proxy could edit the body, drop the field and get a verdict for the edited body. With real tokens this doesn't arise: the hash is inside Google's signed verdict.

Mock tokens are unsigned — lab only. The `/api/lab/*` endpoints have no auth; keep the server on 127.0.0.1.

**Real tokens:** `DW_VERDICT_MODE=google`, `GOOGLE_APPLICATION_CREDENTIALS=service-account.json` (Cloud project linked in Play Console; `service-account*.json` is git-ignored), and the app built with `-Pdemowallet.cloudProjectNumber=<number>`. Calls `playintegrity.googleapis.com/v1/com.demo.wallet:decodeIntegrityToken`.

## Lab simplifications (say them out loud if asked)

- **The grant is a tap.** `/api/agent-tokens` trusts the `X-Actor: user` header, which the client sets. Any code holding the session could mint a grant. In production, mint grants only against a biometric-signed consent (the same Keystore key and `BiometricPrompt` flow as step-up), or on a separate, user-only channel.
- **The step-up key is registered at every sign-in, unattested.** The server accepts whatever public key the app sends at login, so a client with its own software key could confirm its own step-ups. The *binding* (signature over challenge + transfer hash) is real; the key's provenance isn't checked. In production: register the key once at enrollment and verify its Android key attestation chain (hardware-backed, user-auth-bound) before trusting it.
- **No behavior layer on the server.** A script that calls the API as `actor=user` on a clean, certified phone isn't caught here; that's what Lab 3's behavior layer adds.
- **Mock verdicts** (above) and an in-memory, single-account state.

## Scenarios (asserted in `tests/test_service.py`)

Emulator RASP unless noted, €20 transfer.

| scenario | score | decision |
|---|---|---|
| Lab 2 app, profile `none` (no verdict) | 55 | step_up |
| Lab 2 app, profile `emulator` | 60 | step_up |
| profile `device_ok` | 25 | monitor |
| `device_ok`, real phone | 0 | allow |
| assistant, no agent token, `device_ok` | 50 | step_up |
| assistant with agent token, `device_ok` | 35 | monitor |
| `controlled`, real phone | 30 | step_up |
| Frida still attached + assistant, `emulator` | 100 | block |
| lab1-start app (no integrity field) + Frida + assistant | 95 | block |
| same with `DW_SERVER_CHECKS=` (client decides) | 0 | allow |

## Settings (`DW_*` environment variables)

| variable | default | |
|---|---|---|
| `DW_VERDICT_MODE` | `mock` | `mock` or `google` |
| `DW_MOCK_VERDICT` | `emulator` | profile above |
| `DW_SERVER_CHECKS` | `integrity,rasp,agent` | empty = server trusts the client (Lab 1 "before") |
| `DW_INTEGRITY_REQUIRED` | `1` | `0`: a body without `integrity` isn't penalized |
| `DW_AGENT_LIMIT_CENTS` | `10000` | slide 18 agent limit (€100); keep equal to the app's `demowallet.agentLimitCents` |
| `DW_USER_LIMIT_CENTS` | `100000` | |
| `DW_AGENT_TOKEN_TTL_SECONDS` / `_MAX_TTL_SECONDS` | `300` / `600` | |
| `DW_AGENT_TOKEN_SECRET` | random per start | set it to keep tokens valid across restarts |
| `DW_VERDICT_MAX_AGE_SECONDS` / `DW_RASP_MAX_AGE_SECONDS` | `300` / `120` | |
| `DW_PACKAGE_NAME`, `DW_STARTING_BALANCE_CENTS` | `com.demo.wallet`, `245000` | |

## Files

`app.py` FastAPI routes · `service.py` endpoint logic and state · `verify.py` canonical hash, token decoders, verdict checks (Lab 2 block marked `LAB 2`) · `rasp.py` · `agent_tokens.py` · `risk.py` weights and bands · `stepup.py` ECDSA confirmation · `mock_token.py` CLI · `tests/`.
