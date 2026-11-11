# DemoWallet (Android)

Kotlin + Jetpack Compose, package `com.demo.wallet`, minSdk 30, target 35.
Builds `app/build/outputs/apk/debug/wallet.apk`.

```bash
cd android
./gradlew assembleDebug          # build wallet.apk
./gradlew installDebug           # install on the running emulator
./gradlew testDebugUnitTest      # JVM tests: assistant parser, transfer hash, mock step-up
```

Open the `android/` folder in Android Studio to run it from the IDE.

## Lab switches (`gradle.properties`, or `-P` on the command line)

| Property | lab1-start | lab2-start | Meaning |
|---|---|---|---|
| `demowallet.integrityBinding` | `false` | `true` | Bind a Play Integrity token to each transfer's hash (`WalletApi.kt`) |
| `demowallet.cloudProjectNumber` | `0` | `0` | Cloud project linked in Play Console; `0` sends `NOT_CONFIGURED` |
| `demowallet.apiBaseUrl` | `mock` | `mock` | `mock` = in-app fake server; `http://10.0.2.2:8000` = `server/` on the host |

## Emulator setup

- **Lab 1 (rooted):** a *Google APIs* system image (it ships `su`, so `Guard.isRooted()` is true and the app refuses to run until hooked).
- **Normal run:** a *Google Play* system image (no `su`).
- **Step-up confirmation:** Settings → Security → set a PIN, then add a fingerprint; touch the sensor from Extended controls → Fingerprint. Sign in again after enrolling.

The app is signed with the shared lab key in `keystore/` (password `android`) so the RASP signature check is identical for every attendee. Never ship a committed key.
