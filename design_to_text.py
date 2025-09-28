#!/usr/bin/env python3
# design_to_text.py
"""
Utility: Print the `design_text` field from a design JSON.
Assumes apply_text_change.py (or design generation) has already inserted it.
"""

import json, sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python design_to_text.py path/to/design.json")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    d = json.load(open(path, encoding="utf-8"))
    txt = d.get("design_text")
    if not txt:
        print("[no design_text field found in JSON]")
    else:
        print(txt)
