"""Count lines and words in every text file of a folder.

Usage: python folder_stats.py <folder>
The agent passes the user's folder as the first argument automatically.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows = []
for p in sorted(root.rglob("*")):
    if not p.is_file():
        continue
    if any(part.startswith(".") for part in p.relative_to(root).parts):
        continue  # skip hidden files like .DS_Store
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue  # skip binary files like images
    rows.append((str(p.relative_to(root)), len(text.splitlines()), len(text.split())))

width = max([len(name) for name, _, _ in rows] + [5])
print(f"{'file':<{width}}  lines  words")
for name, lines, words in rows:
    print(f"{name:<{width}}  {lines:>5}  {words:>5}")
print(f"{'TOTAL':<{width}}  {sum(r[1] for r in rows):>5}  {sum(r[2] for r in rows):>5}")
print(f"({len(rows)} files)")
