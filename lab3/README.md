# Lab 3 · Score it

Build a risk score, tune its thresholds, and check who you end up challenging. Browser only: Google Colab, no install, no Google Cloud.

| File | What it is |
|---|---|
| `risk_lab.ipynb` | The attendee notebook. Four short ✏️ TODO cells; every cell runs as-is. |
| `risk_lab_solution.ipynb` | Same notebook, completed, with outputs. |
| `sessions.csv` | 6,200 synthetic transfer attempts (written by `generate_sessions.py`). |
| `generate_sessions.py` | The seeded generator (numpy + pandas). `python3 lab3/generate_sessions.py` rewrites `sessions.csv`. |
| `checkpoints/lab3-step2/risk_lab.ipynb` | Checkpoint for the `lab3-step2` branch: step 1 filled in, step 2 open. |
| `tools/` | Maintainer scripts: `build_notebooks.py` (builds all three notebooks from one source) and `run_notebook.py` (runs a notebook top to bottom without Jupyter). |

## Open it in Colab

`https://colab.research.google.com/github/tahirjilani/lab-repo/blob/main/lab3/risk_lab.ipynb`

(Solution: same URL with `risk_lab_solution.ipynb`. Checkpoint: `blob/lab3-step2/lab3/risk_lab.ipynb`.)

The notebook builds the dataset itself from a copy of `generate_sessions.py`, so once Colab has opened it there are no further downloads. Run from a clone, it reads `sessions.csv` instead. Either way it prints a fingerprint (`251dd26c13fb`) so you can see it's the same table.

## The data

Every row is one transfer attempt as the DemoWallet server sees it: Play Integrity verdict, RASP flags, agent identity, the transfer, plus derived behavioral features (timing and shape, never content).

| `cohort` | `label` | Rows |
|---|---|---|
| human | human | 4,300 |
| screen_reader | human | 300 |
| legitimate_agent | legitimate_agent | 1,000 |
| bot (`bot_kind`: script 210, a11y_agent 240, farm 150) | bot | 600 |

It answers "human or not", never "which human": there are no user identifiers. The cohorts overlap on purpose: phone-farm bots pass every device check, and screen-reader users look "tidy" because their actions arrive through an accessibility service.

## Maintaining

Edit cells in `tools/build_notebooks.py`, never the `.ipynb` files, then:

```bash
python3 lab3/generate_sessions.py        # only if the generator changed
python3 lab3/tools/build_notebooks.py    # writes all three notebooks, runs the solution, saves its outputs
python3 lab3/tools/run_notebook.py lab3/risk_lab.ipynb --no-csv   # check the Colab path
```

The baseline weights and bands are copied from `server/risk.py`, `verify.py`, `rasp.py` and `agent_tokens.py`. If those change, update the `server_layers` cell.
