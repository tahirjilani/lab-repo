# Lab 3 · Score it (18 min, browser only)

**Goal:** the server from Labs 1–2 decides on device and agent evidence. Add a **behavior** layer, tune the thresholds, and then check *who* you end up challenging: bots, people, or legitimate agents.

**Where:** Google Colab. No install, no Google Cloud, no emulator.

[**Open `risk_lab.ipynb` in Colab**](https://colab.research.google.com/github/tahirjilani/lab-repo/blob/main/lab3/risk_lab.ipynb)

Sign in with any Google account, then **Runtime → Run all**. Every cell runs as-is; the ✏️ **TODO** cells are where you make changes.

## The data

6,200 synthetic transfer attempts, as the DemoWallet server would see them: the Play Integrity verdict, RASP flags, who acted (user or assistant, with or without an agent token), the transfer, and behavior features derived from timing and motion (never content).

Each row is labeled **human**, **legitimate agent** or **bot**. There are no user identifiers: the question is "human or not", never "which human".

The notebook builds the dataset itself when it opens in Colab, so there's nothing else to download. It prints a fingerprint (`251dd26c13fb`) so you know everyone has the same table. From a clone it reads `lab3/sessions.csv` instead (same fingerprint).

## Steps

| Section | Slide | You do |
|---|---|---|
| 0 · The baseline | | Nothing: see what today's server (Labs 1–2, same weights and bands as `server/risk.py`) catches with no behavior layer. |
| 1 · Build the score | 25 | **TODO 1:** give points to the behavior tells. |
| 2 · Choose the thresholds | 25 | **TODO 2:** set the bands: allow < a ≤ monitor < b ≤ step-up < c ≤ block. |
| 3 · Who are you challenging? | 26 | **TODO 3:** run the per-cohort report on your decisions. |
| 4 · Fix it | 26 | **TODO 4:** rewrite the behavior layer so it stops penalizing the wrong people. |

Step 1 shows results by label only. Section 3 is where the cohorts appear; don't skip ahead.

**Optional ML track** at the end: a logistic regression as the behavior layer, compared with your hand-built one. It needs scikit-learn, which Colab has; the cells skip cleanly where it isn't installed.

## Fallen behind?

Open the **`lab3-step2`** checkpoint: sections 1–2 are filled in, so you can start at section 3.

[Open the checkpoint in Colab](https://colab.research.google.com/github/tahirjilani/lab-repo/blob/lab3-step2/lab3/risk_lab.ipynb)

The completed notebook with outputs: [`risk_lab_solution.ipynb`](https://colab.research.google.com/github/tahirjilani/lab-repo/blob/main/lab3/risk_lab_solution.ipynb).

## Running it locally instead

```bash
pip install jupyter numpy pandas matplotlib scikit-learn
jupyter notebook lab3/risk_lab.ipynb
```

Details on the dataset, the generator and how the notebooks are built: [`lab3/README.md`](../lab3/README.md).
