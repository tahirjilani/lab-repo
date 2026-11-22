"""Synthetic DemoWallet transfer sessions for Lab 3 · Score it.

Every row is one transfer attempt as the server would see it: the device and
runtime evidence the app already sends (Play Integrity verdict, RASP flags,
agent identity) plus derived behavioral features. Derived features only, never
content: timing and shape, not what was typed. The question is "human or not",
never "which human".

Cohorts (`cohort`) and labels (`label`):
  human             people using the app themselves                        label=human
  screen_reader     people using a screen reader (accessibility service)   label=human
  legitimate_agent  the in-app assistant acting for the user               label=legitimate_agent
  bot               malicious automation (see `bot_kind`)                  label=bot

The data is synthetic and seeded. Regenerate with:
    python3 lab3/generate_sessions.py            # writes lab3/sessions.csv
The notebook carries an identical copy of make_sessions(), so Colab can build
the same table offline; the fingerprint printed here must match the notebook's.

Requires numpy and pandas only.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

SEED = 2026
COUNTS = {"human": 4300, "screen_reader": 300, "legitimate_agent": 1000, "bot": 600}
BOT_KINDS = {"script": 210, "a11y_agent": 240, "farm": 150}


def make_sessions(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    def pick(n, options, p):
        return rng.choice(np.array(options, dtype=object), size=n, p=p)

    def flag(n, p):
        return (rng.random(n) < p).astype(int)

    def lognorm(n, median, sigma):
        return np.exp(rng.normal(np.log(median), sigma, n))

    def beta(n, a, b):
        return rng.beta(a, b, n)

    def block(cohort, n, kind=""):
        d = {"cohort": [cohort] * n, "bot_kind": [kind] * n}
        human_like = cohort in ("human", "screen_reader", "legitimate_agent")

        # ── context ──
        if cohort == "legitimate_agent":
            d["actor"] = ["assistant"] * n
            d["agent_token"] = pick(n, ["valid", "none"], [0.95, 0.05])
            d["amount_eur"] = lognorm(n, 30, 0.6)
        elif cohort == "bot":
            imp = {"script": 0.20, "a11y_agent": 0.0, "farm": 0.10}[kind]
            d["actor"] = np.where(rng.random(n) < imp, "assistant", "user")
            tok = pick(n, ["forged", "none"], [0.4, 0.6])
            d["agent_token"] = np.where(d["actor"] == "assistant", tok, "none")
            d["amount_eur"] = lognorm(n, 180, 0.9)
        else:
            d["actor"] = ["user"] * n
            d["agent_token"] = ["none"] * n
            d["amount_eur"] = lognorm(n, 60, 1.0)
        d["new_payee"] = flag(n, {"human": 0.12, "screen_reader": 0.12,
                                  "legitimate_agent": 0.08, "bot": 0.7}[cohort])

        # ── layer 1: device integrity (Play Integrity verdict) ──
        if human_like:
            d["integrity"] = pick(n, ["device_ok", "basic", "no_label", "missing"], [0.97, 0.017, 0.008, 0.005])
            d["app_recognized"] = flag(n, 0.997)
            d["device_activity"] = pick(n, [1, 2, 3, 4], [0.85, 0.14, 0.01, 0.0])
        elif kind == "script":
            d["integrity"] = pick(n, ["device_ok", "basic", "no_label", "missing"], [0.10, 0.20, 0.55, 0.15])
            d["app_recognized"] = flag(n, 0.80)
            d["device_activity"] = pick(n, [1, 2, 3, 4], [0.4, 0.3, 0.2, 0.1])
        elif kind == "a11y_agent":
            d["integrity"] = pick(n, ["device_ok", "basic", "no_label", "missing"], [0.78, 0.12, 0.07, 0.03])
            d["app_recognized"] = flag(n, 0.98)
            d["device_activity"] = pick(n, [1, 2, 3, 4], [0.6, 0.3, 0.08, 0.02])
        else:  # farm: real, clean phones on a rack
            d["integrity"] = pick(n, ["device_ok", "basic", "no_label", "missing"], [0.85, 0.08, 0.05, 0.02])
            d["app_recognized"] = flag(n, 0.98)
            d["device_activity"] = pick(n, [1, 2, 3, 4], [0.15, 0.25, 0.35, 0.25])

        # accessibility: any service on, and whether Play says an app from outside Play can control the device
        a11y_p = {"human": 0.06, "screen_reader": 1.0, "legitimate_agent": 0.06,
                  "script": 0.10, "a11y_agent": 1.0, "farm": 0.30}[kind or cohort]
        d["accessibility_service_on"] = flag(n, a11y_p)
        unk_p = {"human": 0.10, "screen_reader": 0.06, "legitimate_agent": 0.10,
                 "script": 0.5, "a11y_agent": 0.45, "farm": 0.5}[kind or cohort]
        d["unknown_controlling_app"] = d["accessibility_service_on"] * flag(n, unk_p)

        # ── layer 2: RASP ──
        rasp_p = {  # rooted, emulator, hooked, debugger, signature_invalid
            "human": (0.015, 0.002, 0.001, 0.0005, 0.001),
            "screen_reader": (0.015, 0.002, 0.001, 0.0005, 0.001),
            "legitimate_agent": (0.015, 0.002, 0.001, 0.0005, 0.001),
            "script": (0.50, 0.60, 0.45, 0.05, 0.15),
            "a11y_agent": (0.08, 0.02, 0.03, 0.0, 0.02),
            "farm": (0.15, 0.03, 0.05, 0.0, 0.02),
        }[kind or cohort]
        for col, p in zip(["rasp_rooted", "rasp_emulator", "rasp_hooked", "rasp_debugger"], rasp_p[:4]):
            d[col] = flag(n, p)
        d["rasp_signature_ok"] = 1 - flag(n, rasp_p[4])

        # ── layer 3: behavior (derived features only) ──
        a11y = d["accessibility_service_on"]
        if cohort == "human":
            d["a11y_action_ratio"] = np.where(a11y == 1, beta(n, 1, 25), 0.0)
            d["touch_interval_cv"] = lognorm(n, 0.60, 0.35)
            pasted = flag(n, 0.05)
            d["keystroke_interval_cv"] = np.where(pasted == 1, 0.0, lognorm(n, 0.45, 0.35))
            d["swipe_linearity"] = beta(n, 9, 3)
            d["time_to_confirm_s"] = lognorm(n, 7.0, 0.6)
            d["screens_before_transfer"] = 2 + rng.poisson(1.2, n)
            d["nav_path"] = pick(n, ["home>send>confirm", "home>contacts>send>confirm", "notification>confirm"],
                                 [0.55, 0.30, 0.15])
            on_desk = flag(n, 0.12)
            d["motion_energy"] = np.where(on_desk == 1, lognorm(n, 0.06, 0.6), lognorm(n, 0.45, 0.5))
        elif cohort == "screen_reader":
            d["a11y_action_ratio"] = beta(n, 18, 2)
            d["touch_interval_cv"] = lognorm(n, 0.24, 0.40)
            dictation = flag(n, 0.25)  # voice or braille input arrives as injected text
            d["keystroke_interval_cv"] = np.where(dictation == 1, 0.0, lognorm(n, 0.28, 0.4))
            d["swipe_linearity"] = beta(n, 30, 2)
            d["time_to_confirm_s"] = lognorm(n, 16.0, 0.6)
            d["screens_before_transfer"] = 3 + rng.poisson(2.0, n)
            d["nav_path"] = pick(n, ["home>send>confirm", "home>contacts>send>confirm", "notification>confirm"],
                                 [0.50, 0.40, 0.10])
            on_desk = flag(n, 0.25)
            d["motion_energy"] = np.where(on_desk == 1, lognorm(n, 0.06, 0.6), lognorm(n, 0.40, 0.5))
        elif cohort == "legitimate_agent":
            d["a11y_action_ratio"] = np.where(a11y == 1, beta(n, 1, 25), 0.0)
            d["touch_interval_cv"] = lognorm(n, 0.50, 0.40)
            d["keystroke_interval_cv"] = lognorm(n, 0.45, 0.35)  # the user typed the chat prompt
            d["swipe_linearity"] = beta(n, 9, 3)
            d["time_to_confirm_s"] = lognorm(n, 1.6, 0.5)  # the assistant pre-fills; one tap
            d["screens_before_transfer"] = np.ones(n, dtype=int)
            d["nav_path"] = ["chat>confirm"] * n
            on_desk = flag(n, 0.12)
            d["motion_energy"] = np.where(on_desk == 1, lognorm(n, 0.06, 0.6), lognorm(n, 0.45, 0.5))
        elif kind == "script":
            d["a11y_action_ratio"] = np.where(a11y == 1, beta(n, 20, 1.5), 0.0)
            d["touch_interval_cv"] = lognorm(n, 0.05, 0.6)
            d["keystroke_interval_cv"] = np.where(flag(n, 0.7) == 1, 0.0, lognorm(n, 0.04, 0.6))
            d["swipe_linearity"] = beta(n, 60, 1)
            d["time_to_confirm_s"] = lognorm(n, 0.6, 0.6)
            d["screens_before_transfer"] = np.ones(n, dtype=int)
            d["nav_path"] = pick(n, ["deeplink>confirm", "home>send>confirm"], [0.8, 0.2])
            d["motion_energy"] = lognorm(n, 0.01, 0.8)
        elif kind == "a11y_agent":  # LLM-driven malicious app working the UI through accessibility
            d["a11y_action_ratio"] = beta(n, 25, 1.5)
            d["touch_interval_cv"] = lognorm(n, 0.20, 0.45)  # LLM latency adds jitter
            d["keystroke_interval_cv"] = np.where(flag(n, 0.85) == 1, 0.0, lognorm(n, 0.15, 0.5))
            d["swipe_linearity"] = beta(n, 30, 1.5)
            d["time_to_confirm_s"] = lognorm(n, 4.5, 0.6)
            d["screens_before_transfer"] = 2 + rng.poisson(1.0, n)
            d["nav_path"] = pick(n, ["home>send>confirm", "home>contacts>send>confirm"], [0.7, 0.3])
            in_pocket = flag(n, 0.4)
            d["motion_energy"] = np.where(in_pocket == 1, lognorm(n, 0.30, 0.6), lognorm(n, 0.05, 0.7))
        else:  # farm: adb/HID taps with added jitter on racked phones
            d["a11y_action_ratio"] = np.where(a11y == 1, beta(n, 15, 2), beta(n, 1, 40))
            d["touch_interval_cv"] = lognorm(n, 0.35, 0.45)
            d["keystroke_interval_cv"] = lognorm(n, 0.20, 0.5)
            d["swipe_linearity"] = beta(n, 20, 2)
            d["time_to_confirm_s"] = lognorm(n, 2.5, 0.6)
            d["screens_before_transfer"] = 1 + rng.poisson(0.8, n)
            d["nav_path"] = pick(n, ["deeplink>confirm", "home>send>confirm"], [0.5, 0.5])
            d["motion_energy"] = lognorm(n, 0.02, 0.7)
        return pd.DataFrame(d)

    parts = [block(c, n) for c, n in COUNTS.items() if c != "bot"]
    parts += [block("bot", n, k) for k, n in BOT_KINDS.items()]
    df = pd.concat(parts, ignore_index=True)
    df = df.iloc[rng.permutation(len(df))].reset_index(drop=True)
    df["bot_kind"] = df["bot_kind"].replace("", "none")

    df.insert(0, "session_id", [f"s{i:05d}" for i in range(1, len(df) + 1)])
    df.insert(1, "label", df["cohort"].map({"human": "human", "screen_reader": "human",
                                            "legitimate_agent": "legitimate_agent", "bot": "bot"}))
    df["amount_eur"] = df["amount_eur"].clip(1, 5000).round(2)
    for col in ["a11y_action_ratio", "touch_interval_cv", "keystroke_interval_cv", "swipe_linearity", "motion_energy"]:
        df[col] = df[col].clip(0, 1.5 if "cv" in col else 1).round(3)
    df["time_to_confirm_s"] = df["time_to_confirm_s"].clip(0.1, 120).round(2)
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str)
    int_cols = ["new_payee", "app_recognized", "device_activity", "accessibility_service_on",
                "unknown_controlling_app", "rasp_rooted", "rasp_emulator", "rasp_hooked", "rasp_debugger",
                "rasp_signature_ok", "screens_before_transfer"]
    df[int_cols] = df[int_cols].astype(int)
    return df


def fingerprint(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()[:12]


if __name__ == "__main__":
    import sys
    from pathlib import Path

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("sessions.csv")
    df = make_sessions()
    df.to_csv(out, index=False)
    print(f"wrote {out}  rows={len(df)}  fingerprint={fingerprint(df)}")
    print(df["cohort"].value_counts().to_string())
