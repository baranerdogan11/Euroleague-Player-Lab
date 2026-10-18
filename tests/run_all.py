"""Runs every Python self-test in tests/ (each tests/test_*.py as its own process), so a new test file is picked up by
the PR checks and the game-night update without editing either workflow. test_site.py is left out: it needs a season
argument and Chrome, and the workflows run it on its own.
usage: python tests/run_all.py
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = {"test_site.py"}

files = sorted(f for f in glob.glob(os.path.join(HERE, "test_*.py")) if os.path.basename(f) not in SKIP)
failed = []
for f in files:
    name = os.path.basename(f)
    print(f"== {name}", flush=True)
    t = time.time()
    code = subprocess.call([sys.executable, f])
    print(f"== {name}: {'ok' if code == 0 else f'FAILED (exit {code})'} in {time.time() - t:.1f}s", flush=True)
    if code:
        failed.append(name)

print(f"{len(files) - len(failed)} of {len(files)} test files passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
sys.exit(1 if failed else 0)
