# DemoWallet lab: Securing AI-Driven Mobile Experiences

Hands-on lab repo for the DSC Europe session **"Securing AI-Driven Mobile Experiences: From Agent Actions to Runtime Protection"** (Tahir Jilani).

**DemoWallet** is a fictional Android fintech wallet with an AI assistant that can move money ("Send €200 to Ana"). The repo has everything the three labs need:

- **`android/`**: the app (Kotlin, Jetpack Compose, package `com.demo.wallet`, builds `wallet.apk`). It collects signals (Play Integrity, RASP flags, who is acting) and never decides on its own.
- **`server/`**: the verification server (Python, FastAPI). It decides: allow, monitor, step-up or block.
- **`lab3/`**: a synthetic session dataset and a risk-scoring notebook that runs in Google Colab.

The talk's thesis in one line: **authentication is a moment, risk is continuous. The client collects signals; the server decides.**

> Lab code only. The app ships a committed signing key, the server keeps state in memory and has unauthenticated lab endpoints, and the Play Integrity verdicts are simulated by default. Don't reuse any of it as-is.

## The labs

| Lab | Time | What you do | Branch | Guide |
|---|---|---|---|---|
| 1 · Break it | 10 min, watch-along | Bypass the app's root check with Frida and push a transfer through the assistant, then watch the server catch it | `lab1-start` | [docs/lab1.md](docs/lab1.md) |
| 2 · Harden it | 12 min | Bind a Play Integrity token to the transfer hash in the app, verify it on the server. **No emulator? Part B is Python only.** | `lab2-start` | [docs/lab2.md](docs/lab2.md) |
| 3 · Score it | 18 min, browser only | Build a risk score, tune thresholds, compare false positives per cohort | any (Colab) | [docs/lab3.md](docs/lab3.md) |

## Branches

| Branch | Contents |
|---|---|
| `main` | The full solution: Lab 2 code in place, Play Integrity binding on. |
| `lab1-start` | `main` with Play Integrity binding off. Run the server with `DW_SERVER_CHECKS=` for the "client decides" before. |
| `lab2-start` | `main` with the `LAB 2` blocks in `WalletApi.kt` and `server/verify.py` replaced by TODOs. |
| `lab3-step2` | `main` with Lab 3 step 1 filled in: the escape hatch if you fall behind. |

Every branch carries `server/` and `lab3/`, so you can do any lab from any branch.

## Prerequisites

- **Android Studio** (recent stable) with the Android SDK and an emulator. JDK 17+: Android Studio's bundled JBR works.
- **Python 3.9+** for the server.
- **Lab 2 without Android:** just Python: Part B is a server-side exercise with tests.
- **Lab 1 only:** `frida-tools` (pinned in [`lab1/requirements.txt`](lab1/requirements.txt)) and a matching `frida-server`.
- **Lab 3 only:** a Google account for Colab. Nothing to install.

No Google Cloud project is needed: the server simulates Play Integrity verdicts unless you configure the real API.

## Quick start

Full walkthrough with emulator images, fingerprint enrollment and troubleshooting: **[docs/setup.md](docs/setup.md)**.

```bash
git clone https://github.com/tahirjilani/lab-repo.git && cd lab-repo

# 1. Server (terminal 1)
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r server/requirements.txt
pytest server
uvicorn server.app:app --host 127.0.0.1 --port 8000

# 2. App (terminal 2, emulator running)
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"   # macOS
# Windows (PowerShell): see docs/setup.md § Windows
cd android
./gradlew assembleDebug testDebugUnitTest
./gradlew installDebug
adb shell am start -n com.demo.wallet/.MainActivity
```

Sign in with any username and password, then try "Send €20 to Ana" in the assistant.

The app talks to the server at `http://10.0.2.2:8000` (your machine's localhost, as the emulator sees it). For a quick look without Python, build with `-Pdemowallet.apiBaseUrl=mock` to use the in-app fake server instead.

## Lab 3 in Colab

[Open `risk_lab.ipynb` in Colab](https://colab.research.google.com/github/tahirjilani/lab-repo/blob/main/lab3/risk_lab.ipynb) · [checkpoint (`lab3-step2`)](https://colab.research.google.com/github/tahirjilani/lab-repo/blob/lab3-step2/lab3/risk_lab.ipynb) · [solution](https://colab.research.google.com/github/tahirjilani/lab-repo/blob/main/lab3/risk_lab_solution.ipynb)

## Repo layout

```
android/        DemoWallet app (see android/README.md for the gradle switches)
server/         verification server (see server/README.md for endpoints and DW_* settings)
lab1/           Lab 1: frida-tools pin; the bypass script goes here
lab3/           dataset, notebooks, generator
docs/           setup and lab guides
```
