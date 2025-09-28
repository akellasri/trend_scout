#!/usr/bin/env python3
"""
batch_agent2_payloads.py

Iterates through all payloads in agent2_inputs/ and runs test_agent2_payload.py on each.
Generates design JSONs for all payloads (80+).
"""

import os, sys, time, subprocess
from pathlib import Path

payload_dir = Path("agent2_inputs")
script = "test_agent2_payload.py"

if not payload_dir.exists():
    print("No agent2_inputs/ directory found.")
    sys.exit(1)

payloads = sorted(payload_dir.glob("*.json"))
print(f"Found {len(payloads)} payloads.")

for i, p in enumerate(payloads, start=1):
    print(f"\n=== [{i}/{len(payloads)}] Processing {p.name} ===")
    try:
        subprocess.run([sys.executable, script, str(p)], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running {p.name}: {e}")
    # polite small pause to avoid rate limits
    time.sleep(2)
