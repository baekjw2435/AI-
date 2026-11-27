#!/usr/bin/env python3
"""Run the included real-dictionary smoke example; no search/compiler needed."""
import json
from pathlib import Path

from verify_v2 import verify_v2

base = Path(__file__).resolve().parent
example = base / "examples" / "smoke"
result = verify_v2(base / "words.txt", example / "position.json",
                   example / "proof.jsonl", example / "input.txt")
print(json.dumps(result, ensure_ascii=False, indent=2))
