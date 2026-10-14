"""Find remaining unchecked - [ ] todos.

Usage: python find_todos.py <folder>
The agent passes the user's folder as the first argument automatically.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
todos = []  # (file, line number, todo text)

for p in sorted(root.rglob("*")):
    if not p.is_file():
        continue
    if any(part.startswith(".") for part in p.relative_to(root).parts):
        continue  # skip hidden files like .DS_Store
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        continue  # skip binary files like images

    for num, line in enumerate(lines, start=1):
        stripped = line.lstrip()  # allow indented sub-items
        if stripped.startswith("- [ ]"):
            text = stripped[len("- [ ]"):].strip()
            todos.append((str(p.relative_to(root)), num, text))

if not todos:
    print("No unchecked todos found.")
else:
    for name, num, text in todos:
        print(f"{name}:{num}: {text}")
    files = len({name for name, _, _ in todos})
    print(f"({len(todos)} unchecked todos in {files} file(s))")