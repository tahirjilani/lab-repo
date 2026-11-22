# DemoWallet lab server

The server half of the talk's thesis: **the client collects signals, the server decides.**
FastAPI, in-memory state, one lab account (`acc-001`, €2,450.00), reset on restart.

```bash
# from the repo root
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
pytest server                                   # 78 tests
uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Point the app at it: `cd android && ./gradlew installDebug -Pdemowallet.apiBaseUrl=http://10.0.2.2:8000`
(the emulator's 10.0.2.2 is your Mac's localhost).

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

`dwat1.<claims>.<HMAC-SHA256>` with `account, agent_id, action, max_amount_cents, currency, payee_id?, iat, exp`. Max amount is capped by the agent limit (deck slide 18, `DW_AGENT_LIMIT_CENTS`, default €100), TTL by `DW_AGENT_TOKEN_MAX_TTL_SECONDS` (600). Single use. Out of scope (amount, payee, action, agent id) or expired → step-up; forged or another account's token → block. The current app does not send `X-Agent-Token` yet, so every assistant transfer is "no delegation" → step-up.

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

Mock tokens are unsigned — lab only. The `/api/lab/*` endpoints have no auth; keep the server on 127.0.0.1.

**Real tokens:** `DW_VERDICT_MODE=google`, `GOOGLE_APPLICATION_CREDENTIALS=service-account.json` (Cloud project linked in Play Console; `service-account*.json` is git-ignored), and the app built with `-Pdemowallet.cloudProjectNumber=<number>`. Calls `playintegrity.googleapis.com/v1/com.demo.wallet:decodeIntegrityToken`.

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
| `DW_AGENT_LIMIT_CENTS` | `10000` | slide 18 agent limit, still TBD |
| `DW_USER_LIMIT_CENTS` | `100000` | |
| `DW_AGENT_TOKEN_TTL_SECONDS` / `_MAX_TTL_SECONDS` | `300` / `600` | |
| `DW_AGENT_TOKEN_SECRET` | random per start | set it to keep tokens valid across restarts |
| `DW_VERDICT_MAX_AGE_SECONDS` / `DW_RASP_MAX_AGE_SECONDS` | `300` / `120` | |
| `DW_PACKAGE_NAME`, `DW_STARTING_BALANCE_CENTS` | `com.demo.wallet`, `245000` | |

## Files

`app.py` FastAPI routes · `service.py` endpoint logic and state · `verify.py` canonical hash, token decoders, verdict checks (Lab 2 block marked `LAB 2`) · `rasp.py` · `agent_tokens.py` · `risk.py` weights and bands · `stepup.py` ECDSA confirmation · `mock_token.py` CLI · `tests/`.
