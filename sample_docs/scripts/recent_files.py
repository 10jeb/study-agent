"""List the most recently modified files in the folder.

Usage: python recent_files.py <folder>
The agent passes the user's folder as the first argument automatically.

This answers questions like "what did I work on last?", which the agent
can't answer from list_files alone, because that only shows names and sizes.
"""
import sys
from datetime import datetime
from pathlib import Path

LIMIT = 5

root = Path(sys.argv[1]).resolve()
files = [
    p for p in root.rglob("*")
    if p.is_file()
    and not any(part.startswith(".") for part in p.relative_to(root).parts)
    and p.resolve().is_relative_to(root)   # skip symlinks pointing outside
]
files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

if not files:
    print("No files found.")
for p in files[:LIMIT]:
    modified = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    print(f"{modified}  {p.relative_to(root)}")
