# Lab 2 · Harden it (12 min)

**Goal:** make the app's evidence mean something. The app asks Play Integrity for a verdict **bound to the exact transfer** (its hash), and the server refuses a verdict that was issued for another app, another transfer, or too long ago. A failed or missing verdict **steps up** (you confirm with your fingerprint); it never silently passes and never blocks on its own.

**Branch:** `lab2-start`. You fill in two places, both marked `LAB 2`:

| Part | File | What |
|---|---|---|
| A | `android/app/src/main/java/com/demo/wallet/WalletApi.kt` | Request a Play Integrity token for this transfer's hash (`TODO(Lab 2, A)`) |
| B | `server/verify.py` | Three checks on the decoded token (`TODO(Lab 2, B1)`, `B2`, `B3`) |

Do Part B first if you're short on time: it's Python, needs no rebuild, and `pytest` tells you when it's right.

### No Android Studio? Do Part B only (Python, ~5 min)

Most laptops won't have an emulator ready, and conference Wi-Fi won't download one. You don't need it: Part B is plain Python and its tests are the checker.

```bash
git clone https://github.com/tahirjilani/lab-repo.git && cd lab-repo
git checkout lab2-start
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r server/requirements.txt                   # five small packages, no Google libraries
pytest server --lab2                                     # 7 failing tests = your to-do list
```

Then open `server/verify.py`, fill in B1–B3 (below) and re-run `pytest server --lab2` until it's green. Watch the speaker's screen for Part A and the re-run on slide 24.

Stuck or out of time? `main` is the solution: `git diff lab2-start main -- android/app/src/main/java/com/demo/wallet/WalletApi.kt server/verify.py`.

## 0. Start state (2 min, emulator users)

Normal (**Google Play**) emulator, set up as in [setup.md](setup.md).

```bash
git checkout lab2-start
uvicorn server.app:app --host 127.0.0.1 --port 8000          # terminal 1, venv active (Windows: .venv\Scripts\Activate.ps1)
cd android && ./gradlew installDebug && cd ..                 # terminal 2
adb shell am start -n com.demo.wallet/.MainActivity
```

Sign in and ask the assistant **"Send €20 to Ana"** → **Allow**. The server steps up: **"No integrity verdict sent."** The chip says `integrity: on`, but the request body has no `integrity` field. That's TODO A.

## Part A · Bind the token to the transfer (app, 3 min)

Open `WalletApi.kt` and find `sendTransfer`. Each transfer already has a canonical form and a hash:

```
v1|<account>|<payeeId>|<amountCents>|<currency>|<nonce>|<actor>   →   SHA-256, lowercase hex
```

`IntegrityTokens.tokenFor(requestHash)` makes a Play Integrity **standard request** with `setRequestHash(requestHash)`, so Google puts that hash inside the signed verdict. It never throws: if it can't get a token (no Cloud project, no Play services, an error), it returns the reason, and that goes to the server as evidence too.

**TODO(Lab 2, A):** replace

```kotlin
val integrityResult: IntegrityResult? = null
```

with a token bound to this transfer when binding is enabled, and nothing when it isn't.

<details><summary>Solution</summary>

```kotlin
val integrityResult: IntegrityResult? =
    if (integrityBindingEnabled) integrity.tokenFor(transfer.requestHash()) else null
```
</details>

Rebuild and try again:

```bash
cd android && ./gradlew installDebug && cd ..
```

Sign in, **"Send €20 to Ana"** → Allow. Still **step-up**, but for a different reason: **"Device fails integrity (no device label); App not recognized by Google Play…"** (score 70).

That's the honest answer, not a bug. With no Cloud project configured (`cloudProjectNumber=0`), the app sends `error: NOT_CONFIGURED`, and the server simulates what Google would say about *this* device: an emulator gets no device-integrity label, and a sideloaded app isn't Play-recognized. The Frida hook from Lab 1 has nothing to do with it. Confirm with your fingerprint and the transfer goes through: failed verdict → step-up, never a hard block.

Now pretend you're on a certified phone with the app from Play:

```bash
curl -s localhost:8000/api/lab/mock-verdict -H 'Content-Type: application/json' -d '{"profile":"device_ok"}'
```

**"Send €20 to Ana"** again → **monitor** (35): sent, logged for review because it's still an emulator and an agent.

## Part B · Make the server check the binding (server, 5 min)

The verdict is only useful if the server checks that it belongs to *this* request. Open `server/verify.py`, function `check_payload`. `rd` is the token's `requestDetails`; `expected_hash` is the hash the **server** recomputed from the transfer in the body (it never trusts the app's own `clientRequestHash`).

| TODO | Check | If it fails |
|---|---|---|
| **B1** | `rd["requestPackageName"]` is `package_name` (`com.demo.wallet`); the field can be spoofed in transit, so the server checks it | `package_mismatch` → **block** |
| **B2** | `rd["requestHash"]` equals `expected_hash` (use `hmac.compare_digest`) | `hash_mismatch` → **block**: the token was made for a different transfer |
| **B3** | `rd["timestampMillis"]` (epoch ms, as a string) is at most `max_age_s` old and not more than 60 s in the future | `stale` → **step-up** |

The exact `_sig(...)` lines to return or append are in the TODO comments.

Check your work. The tests that need these checks are skipped by a plain `pytest server` on this branch; `--lab2` runs them:

```bash
pytest server --lab2
```

Seven tests fail before you start and all pass when you're done. Two of them are the attacks this stops; read them in `server/tests/test_service.py`:

- `test_request_hash_mismatch_is_blocked`: a genuine token from a €1 transfer lifted onto a €200 one → **block**, money stays put.
- `test_body_altered_in_transit_is_blocked`: a proxy changes €20 to €2,000 after the app hashed it → **block**.

  In this lab the verdict is simulated, so the server binds it to the hash the app reports (`clientRequestHash`); a body without that hash gets no simulated verdict at all (step-up). With real tokens the hash sits inside Google's signed verdict and the client can't touch it.

Restart uvicorn (Ctrl-C, start again) to load your code; the verdict profile goes back to `emulator`, and you have to sign in again. The honest app's transfers behave the same as before: the checks only bite when something doesn't match.

## Slide 24 · the same attack, after Lab 2 (presenter)

Re-run Lab 1's attack against the hardened build. Do the reinstall while the room works on Part B.

On the **rooted (Google APIs)** emulator from Lab 1, with frida-server still running:

```bash
git stash                                                # only if you edited lab2-start live
git checkout main                                        # the Lab 2 solution: binding on
cd android && ./gradlew installDebug && cd ..            # ~1 min; replaces the lab1-start build
uvicorn server.app:app --host 127.0.0.1 --port 8000      # all checks on, profile "emulator"
frida -U -f com.demo.wallet -l lab1/bypass.js
```

1. Sign in. **"Send €200 to Ana"** → **Allow**. **Blocked, score 100**: instrumentation detected (40) + device fails integrity, no device label (35) + €200 outside the €100 delegation (30). The hook still hides root; it just doesn't matter.
2. Pretend it's a certified phone with the app from Play, **Frida still attached**:

   ```bash
   curl -s localhost:8000/api/lab/mock-verdict -H 'Content-Type: application/json' -d '{"profile":"device_ok"}'
   ```

3. **"Send €200 to Ana"** → **Allow** again. **Step-up, score 70** (hook 40 + out of scope 30). Confirm with the fingerprint (`adb -e emu finger touch 1`) and it goes through. The honest-looking device no longer blocks, but the hook alone still forces a confirmation.

Don't stop Frida for this: on the Google APIs image the app would go straight back to "This device appears to be rooted". And don't do it on the `lab1-start` build: that build sends no verdict at all, so switching the profile changes nothing (it stays at block 100).

## The other evidence: RASP flags (look, don't code)

Every request already carries the app's RASP flags twice: in the `X-RASP` header and in the transfer body (`rasp: {rooted, emulator, debugger, signatureValid, hooked, …}`). In the server window you'll see them on each request. The server scores them as one layer next to integrity and agent identity (`server/rasp.py`), and if the header and body disagree, that disagreement is itself a signal. The app never acts on them itself: it reports, the server decides.

## Takeaways

- **Bind the verdict to the action.** A verdict that says "good device" without saying "for this transfer" can be replayed onto any transfer.
- **Check the binding on the server**, from your own recomputation of the request, plus the package name and freshness.
- **Missing or failed verdict → step-up, not block.** Devices without Play services, emulators, rooted-but-honest users exist; a confirmation is a fair price, a lockout isn't.
