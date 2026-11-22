# Lab 1 · Break it (10 min, watch-along)

**Goal:** show that a check the client makes for itself is only a suggestion. On a rooted emulator, a few lines of Frida turn off the app's root check and the assistant moves money. Then the same attack against a server that decides for itself.

**Branch:** `lab1-start`, which is `main` with Play Integrity binding off (`demowallet.integrityBinding=false`), so the app sends no integrity evidence at all.

This lab is a demo on the speaker's machine. Follow along on screen; you don't need Frida installed. If you want to repeat it afterwards, see [setup.md § 6](setup.md#6-lab-1-extras-frida).

## Before the session (presenter)

1. **Google APIs** emulator with a PIN and an enrolled fingerprint ([setup.md § 3](setup.md#3-emulators)), and `frida-server` running on it ([setup.md § 6](setup.md#6-lab-1-extras-frida)).
2. Build and install the start state:

   ```bash
   git checkout lab1-start
   cd android && ./gradlew installDebug && cd ..
   ```

3. Two terminals at the repo root with the venv active: one for the server, one for Frida.

## 1. The app refuses to run (1 min)

```bash
adb shell am start -n com.demo.wallet/.MainActivity
```

The app shows **"This device appears to be rooted"**. One call decided that: `Guard.isRooted()`, on the device.

## 2. "Before": the server trusts the client (4 min)

Start the server with no server-side checks. This is what many apps effectively do: whatever the client says, goes.

```bash
DW_SERVER_CHECKS= uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Launch the app under Frida with the bypass script:

```bash
frida -U -f com.demo.wallet -l lab1/bypass.js
```

<!-- =========================================================================== -->
<!-- TODO(Tahir): lab1/bypass.js: the presenter's Frida script, written by Tahir. -->
<!-- Show it on screen here. It hooks com.demo.wallet.Guard.isRooted() → false.  -->
<!-- =========================================================================== -->

> **Script: `lab1/bypass.js`** (written by Tahir; added before the session). It hooks `com.demo.wallet.Guard.isRooted()` to return `false`. See [`lab1/README.md`](../lab1/README.md) for what it targets.

The root screen is gone. Sign in, then in the assistant:

1. Type or tap **"Send €200 to Ana"**.
2. The assistant asks for permission. Tap **Allow**: the grant shows up in the chat, then the transfer goes out.
3. **Allowed, score 0.** €200 left the account. The server log shows `X-RASP: … root=0 … hook=1`: the app *reported* the hook, but with `DW_SERVER_CHECKS=` nobody looked.

Note the signal chips at the top of the home screen: `root ✓` (the hook hid it) but `hook!`.

## 3. "After": the server decides (4 min)

Stop the server (Ctrl-C) and start it with all checks on:

```bash
uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Same app, same Frida session (sign out and in again: the restarted server forgot the session). **"Send €200 to Ana"** → Allow:

**Blocked, score 100.** The reason lists three independent findings, one per layer:

| Layer | Signal | Points |
|---|---|---|
| RASP | Instrumentation detected (Frida's port, threads, memory maps) | 40 |
| Integrity | No integrity verdict sent (this branch doesn't send one) | 30 |
| Agent | €200 is outside the assistant's delegation of €100 | 30 |

Each layer counts its worst signal; the layers add up (capped at 100). `≥ 90` blocks. Hooking `isRooted` changed nothing here: the server never asked the app whether it was rooted.

See it from the server's side:

```bash
curl -s localhost:8000/api/lab/decisions | python3 -m json.tool
```

**Variation:** "Send €20 to Ana" under Frida is **step-up, score 80** (the €20 is within the delegation, so the agent layer adds only 10). The hook alone already forces a confirmation; the server never silently lets it through.

## Takeaways

- A local check is a speed bump. Anything that runs on the device can be changed by whoever controls the device.
- Report signals, don't act on them locally. The app sent `hook=1` in both runs; only the server's decision changed.
- Lab 2 adds the evidence this branch is missing: a Play Integrity verdict bound to the exact transfer.

## Reset

```bash
adb shell am force-stop com.demo.wallet
git checkout main     # or lab2-start for the next lab
```
