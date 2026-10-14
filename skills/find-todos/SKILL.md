---
name: find-todos
description: Find every unchecked - [ ] in a todo list across all files.
---

# Find todos

Report to the user the text coinciding with each unchecked - [ ] in the order in which they appear per file.

1. Call run_script with name "find_todos.py" and skill "find-todos".
2. If multiple files have todos, report from files in chronological order of when they were last edited, with the oldest file being reported first.
3. If the script fails, show the user the error instead of guessing.