"""Minimal notebook runner for maintainers (no Jupyter needed).

Executes every code cell of an .ipynb top to bottom in one namespace, the way
"Run all" does, and stores stdout, the value of a cell's last expression and
matplotlib figures as nbformat-4 outputs. Stops at the first error.

    python3 lab3/tools/run_notebook.py lab3/risk_lab.ipynb              # check only
    python3 lab3/tools/run_notebook.py lab3/risk_lab_solution.ipynb --write   # keep outputs

Runs with the notebook's folder as the working directory, so the cell that
loads sessions.csv finds it; pass --no-csv to hide the CSV and exercise the
Colab path (generate in the notebook).
"""
from __future__ import annotations

import argparse
import ast
import base64
import contextlib
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")


def _figures():
    if "matplotlib.pyplot" not in sys.modules:
        return []
    import matplotlib.pyplot as plt

    out = []
    for num in plt.get_fignums():
        buf = io.BytesIO()
        plt.figure(num).savefig(buf, format="png", dpi=100, bbox_inches="tight")
        out.append(base64.b64encode(buf.getvalue()).decode())
    plt.close("all")
    return out


def _display_data(value):
    data = {"text/plain": repr(value)}
    html = getattr(value, "_repr_html_", None)
    if callable(html):
        h = html()
        if h:
            data["text/html"] = h
    return data


def run(path: Path, write: bool, hide_csv: bool) -> float:
    nb = json.loads(path.read_text())
    ns = {"__name__": "__main__", "display": lambda *a: [print(x) for x in a]}
    cwd = os.getcwd()
    os.chdir(path.parent)
    csv = path.parent / "sessions.csv"
    moved = None
    if hide_csv and csv.exists():
        moved = csv.with_suffix(".csv.hidden")
        csv.rename(moved)
    t0 = time.time()
    count = 0
    try:
        for cell in nb["cells"]:
            if cell["cell_type"] != "code":
                continue
            count += 1
            src = "".join(cell["source"])
            outputs = []
            stdout = io.StringIO()
            tree = ast.parse(src)
            quiet = src.rstrip().endswith(";")  # Jupyter: a trailing ; hides the value
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) and not quiet else None
            try:
                with contextlib.redirect_stdout(stdout):
                    exec(compile(tree, f"<cell {count}>", "exec"), ns)
                    value = eval(compile(ast.Expression(last.value), f"<cell {count}>", "eval"), ns) if last else None
            except Exception:
                print(stdout.getvalue())
                print(f"✗ cell {count} failed:\n{src}\n")
                traceback.print_exc()
                raise SystemExit(1)
            if stdout.getvalue():
                outputs.append({"output_type": "stream", "name": "stdout", "text": stdout.getvalue()})
            for png in _figures():
                outputs.append({"output_type": "display_data", "metadata": {},
                                "data": {"image/png": png, "text/plain": "<Figure>"}})
            if value is not None:
                outputs.append({"output_type": "execute_result", "execution_count": count,
                                "metadata": {}, "data": _display_data(value)})
            cell["outputs"] = outputs
            cell["execution_count"] = count
    finally:
        if moved:
            moved.rename(csv)
        os.chdir(cwd)
    elapsed = time.time() - t0
    if write:
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    print(f"✓ {path.name}: {count} code cells ran cleanly in {elapsed:.1f}s")
    return elapsed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("notebook", type=Path)
    ap.add_argument("--write", action="store_true", help="save outputs into the notebook")
    ap.add_argument("--no-csv", action="store_true", help="hide sessions.csv (Colab path)")
    a = ap.parse_args()
    run(a.notebook.resolve(), a.write, a.no_csv)
