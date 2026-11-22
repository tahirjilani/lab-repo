# Setup

Do this before the session: it needs downloads that conference Wi-Fi won't enjoy. Budget 30–45 minutes, most of it waiting for Android Studio and a system image.

Commands are for macOS. On Linux and Windows the steps are the same; only the paths differ.

## 1. Get the repo

```bash
git clone https://github.com/tahirjilani/lab-repo.git
cd lab-repo
git branch -a        # main, lab1-start, lab2-start, lab3-step2
```

## 2. Android Studio, SDK and JDK

1. Install Android Studio (recent stable). On first launch, let it install the Android SDK, the platform tools (`adb`) and the emulator.
2. In **SDK Manager → SDK Platforms**, install **Android 15 (API 35)**. The app compiles against API 35; its minimum is API 30 (Android 11).
3. Builds need JDK 17 or newer. Android Studio's bundled JBR is fine. For the command line:

   ```bash
   export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
   java -version        # 17 or newer
   ```

4. Tell Gradle where the SDK is. Either set `ANDROID_HOME`, or create `android/local.properties` (it's git-ignored) with an absolute path:

   ```properties
   sdk.dir=/Users/<you>/Library/Android/sdk
   ```

5. Put `adb` on your `PATH`: `export PATH="$HOME/Library/Android/sdk/platform-tools:$PATH"`.

## 3. Emulators

Create them in **Device Manager → Create virtual device** (any Pixel phone). Use **arm64-v8a** images on Apple Silicon and **x86_64** on Intel or AMD machines. API 35 is a good choice; anything from API 30 works.

| Emulator | System image | Used for |
|---|---|---|
| **Rooted** | **Google APIs** (not Google Play) | Lab 1. It ships `su`, so the app shows "This device appears to be rooted" until `Guard.isRooted` is hooked. `adb root` works on it, which `frida-server` needs. |
| **Normal** | **Google Play** | Lab 2 and everyday runs. No `su`, so the app starts normally. |

Both are emulators, so the app's RASP flags always show `emulator!` and the server treats allowed transfers as **monitor**, not allow. That's expected.

### Screen lock and fingerprint (needed for step-up)

When the server asks for confirmation ("step-up"), the app signs the transfer with a key that only unlocks with a fingerprint. Set this up on **each** emulator, **before signing in**:

1. **Settings → Security & privacy → Device unlock → Screen lock → PIN.** Pick any PIN.
2. **Settings → … → Fingerprint Unlock → Add fingerprint.** When it asks you to touch the sensor, open the emulator's **Extended controls (⋯) → Fingerprint** and click **Touch sensor** (repeat until enrolled). From a terminal you can also run `adb -e emu finger touch 1`.
3. Sign in to DemoWallet **after** enrolling. The confirmation key is created at sign-in; if there's no fingerprint yet, the app shows "Couldn't create the confirmation key…". Enroll, sign out, sign in again.

On the confirmation screen, use the same **Touch sensor** button (or `adb -e emu finger touch 1`) when the system sheet appears.

## 4. The server

From the repo root, in its own terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
pytest server                                         # should pass (some tests are skipped on lab2-start; see docs/lab2.md)
uvicorn server.app:app --host 127.0.0.1 --port 8000
```

The window prints every request and response (passwords and tokens redacted), plus one line per decision. Keep it visible: it's half the demo. `DW_LOG_HTTP=compact` shortens it; `off` silences it.

State lives in memory: one account (`acc-001`, €2,450.00), reset whenever you restart the server.

Useful settings (environment variables; full list in [`server/README.md`](../server/README.md)):

| Variable | Default | Use it for |
|---|---|---|
| `DW_SERVER_CHECKS` | `integrity,rasp,agent` | Set it **empty** (`DW_SERVER_CHECKS= uvicorn …`) for Lab 1's "before": the server trusts the client. |
| `DW_MOCK_VERDICT` | `emulator` | Which Play Integrity verdict to simulate (see below). |
| `DW_AGENT_LIMIT_CENTS` | `10000` | The most a user can delegate to the assistant (€100). Keep equal to the app's `demowallet.agentLimitCents`. |

### Switching the simulated Play Integrity verdict

An emulator with a sideloaded app can't get a passing Play Integrity verdict from Google: emulators get no device-integrity label and sideloaded installs are unlicensed. So by default the server simulates the verdict Google would return. Pick a profile at start (`DW_MOCK_VERDICT=device_ok uvicorn …`) or switch it live:

```bash
curl -s localhost:8000/api/lab/mock-verdict -H 'Content-Type: application/json' -d '{"profile":"device_ok"}'
curl -s localhost:8000/api/lab/status
curl -s localhost:8000/api/lab/decisions | python3 -m json.tool     # recent decisions with scores and signals
```

| Profile | Simulates | €20 on an emulator, sent by you | …by the assistant (with its token) |
|---|---|---|---|
| `emulator` (default) | What you really get here: no device label, app not recognized, unlicensed | step-up (60) | step-up (70) |
| `device_ok` | Play-installed app on a certified, locked phone | monitor (25) | monitor (35) |
| `basic` | Rooted phone that still passes basic integrity | monitor (45) | step-up (55) |
| `controlled` | `device_ok`, but an app from outside Play can control the device | step-up (55) | step-up (65) |
| `none` | No verdict at all | step-up (55) | step-up (65) |

Numbers are risk scores (0–100; bands `<25 allow · <50 monitor · <90 step-up · ≥90 block`).

The simulated verdict is bound to the hash the app computed, so a transfer edited in transit still fails the hash check. A missing or failed verdict always steps up; it never passes and never blocks on its own.

## 5. The app

With the server running and an emulator started:

```bash
cd android
./gradlew assembleDebug testDebugUnitTest    # builds app/build/outputs/apk/debug/wallet.apk and runs the JVM tests
./gradlew installDebug
adb shell am start -n com.demo.wallet/.MainActivity
```

Or open the `android/` folder in Android Studio and press Run.

Sign in with any username and password (`tahir` / `demo` is prefilled). The footer shows which backend the app uses and whether Play Integrity binding is on.

**Try it:**

- **"Send €20 to Ana"**: the assistant asks for your permission first. **Allow** grants it a token for one transfer to Ana of at most €20, valid 5 minutes. The grant appears in the chat, then the transfer goes out with it (`X-Agent-Token`).
- **"Send €200 to Ana"**: you can delegate at most €100 (the agent limit), so the assistant gets a €100 token and the €200 transfer is out of scope ("€200.00 exceeds the delegated €100.00"). What happens next depends on the verdict profile: with the default `emulator` profile the layers add up to **block** (35 integrity + 25 emulator + 30 out of scope = 90); with `device_ok` it's **step-up** (55) and you confirm with your fingerprint.
- **Send** button: a transfer you make yourself (no token needed; over €1,000 steps up).

### Gradle switches

Set in `android/gradle.properties`, or override per build with `-P<name>=<value>`:

| Property | Default | Meaning |
|---|---|---|
| `demowallet.apiBaseUrl` | `http://10.0.2.2:8000` | The server. `mock` = in-app fake server (no Python, placeholder rules). |
| `demowallet.integrityBinding` | `true` (`false` on `lab1-start`) | Request a Play Integrity token bound to each transfer's hash. |
| `demowallet.agentLimitCents` | `10000` | Most the user can delegate to the assistant (€100). |
| `demowallet.cloudProjectNumber` | `0` | Cloud project linked in Play Console. `0` = not configured: the app sends `NOT_CONFIGURED` and the server simulates the verdict. |

**Real phone instead of an emulator:** `adb reverse tcp:8000 tcp:8000`, then build with `-Pdemowallet.apiBaseUrl=http://127.0.0.1:8000`.

## 6. Lab 1 extras: Frida

Only for Lab 1 (watch-along; you don't need this to follow). Versions are pinned in [`lab1/requirements.txt`](../lab1/requirements.txt): **frida-tools 14 or newer with Frida 17**. Frida 17 removed the Java bridge from the runtime, but the `frida` command-line REPL still bundles it, which is what Lab 1 uses.

```bash
source .venv/bin/activate
pip install -r lab1/requirements.txt
frida --version                       # e.g. 17.x.y: frida-server must be EXACTLY this version
```

Download `frida-server-<that version>-android-arm64.xz` (Apple Silicon) or `-android-x86_64.xz` (Intel) from the [Frida releases](https://github.com/frida/frida/releases), then, on the **Google APIs** emulator:

```bash
unxz frida-server-*-android-*.xz
adb root
adb push frida-server-*-android-* /data/local/tmp/frida-server
adb shell chmod 755 /data/local/tmp/frida-server
adb shell "/data/local/tmp/frida-server >/dev/null 2>&1 &"
frida-ps -U | head                    # lists processes: it works
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Can't reach http://10.0.2.2:8000 … Is the lab server running?" | Start uvicorn (step 4). It must listen on port 8000. On a real phone use `adb reverse` (step 5). |
| "This device appears to be rooted" on the normal emulator | You're on a Google APIs image. Use a Google Play image, or hook it (Lab 1). |
| "Couldn't create the confirmation key" | Set a PIN and enroll a fingerprint, then sign out and in again. |
| Every transfer steps up | Expected with the default `emulator` profile. Switch to `device_ok` to see monitor. |
| Server restarted, app shows errors | The server forgets sessions on restart. Sign out and in again. |
| `Unsupported class file major version` / JDK errors | Point `JAVA_HOME` at JDK 17+ (step 2). |
| `SDK location not found` | Create `android/local.properties` or set `ANDROID_HOME` (step 2). |
| `frida` can't attach / version mismatch | `frida --version` and frida-server must match exactly. Run `adb root` before starting frida-server. |
