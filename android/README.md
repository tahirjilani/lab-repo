# DemoWallet (Android)

Kotlin + Jetpack Compose, package `com.demo.wallet`, minSdk 30, target 35.
Builds `app/build/outputs/apk/debug/wallet.apk`.

```bash
cd android
./gradlew assembleDebug          # build wallet.apk
./gradlew installDebug           # install on the running emulator
./gradlew testDebugUnitTest      # JVM tests: assistant parser, transfer hash, mock step-up and agent tokens
```

Open the `android/` folder in Android Studio to run it from the IDE.

## Lab switches (`gradle.properties`, or `-P` on the command line)

| Property | main | lab1-start | lab2-start | Meaning |
|---|---|---|---|---|
| `demowallet.integrityBinding` | `true` | `false` | `true` | Bind a Play Integrity token to each transfer's hash (`WalletApi.kt`; a TODO on lab2-start) |
| `demowallet.apiBaseUrl` | `http://10.0.2.2:8000` | same | same | `server/` on the host; `mock` = in-app fake server, no Python |
| `demowallet.agentLimitCents` | `10000` | same | same | Most the user can delegate to the assistant (deck slide 18: €100); keep equal to the server's `DW_AGENT_LIMIT_CENTS` |
| `demowallet.cloudProjectNumber` | `0` | `0` | `0` | Cloud project linked in Play Console; `0` sends `NOT_CONFIGURED` |

## Assistant and agent tokens

Before the assistant moves money it asks you to **Allow** a scoped grant: one transfer, one payee, up to `min(amount, agent limit)`, valid 5 minutes. The app mints it with `POST /api/agent-tokens` as the user (`X-Actor: user`), shows it in the chat, and the transfer carries it as `X-Agent-Token`. See `WalletViewModel.approveGrant` and `WalletApi.grantAssistant`.

## Emulator setup

Full version: [`docs/setup.md`](../docs/setup.md).

- **Lab 1 (rooted):** a *Google APIs* system image (it ships `su`, so `Guard.isRooted()` is true and the app refuses to run until hooked).
- **Normal run:** a *Google Play* system image (no `su`).
- **Step-up confirmation:** Settings → Security → set a PIN, then add a fingerprint; touch the sensor from Extended controls → Fingerprint. Sign in again after enrolling.

The app is signed with the shared lab key in `keystore/` (password `android`) so the RASP signature check is identical for every attendee. Never ship a committed key.
