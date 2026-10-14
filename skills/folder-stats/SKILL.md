---
name: folder-stats
description: Report how many files, lines and words are in the user's folder. Use when the user asks how big their notes are, how much they've written, or for any counts of their files.
---

# Folder stats

Language models are unreliable at counting, so never count lines or words
yourself. Run the script and report its numbers exactly.

1. Call run_script with name "folder_stats.py" and skill "folder-stats".
2. Report the TOTAL row first, in one sentence.
3. Then list the files from most words to fewest.
4. If the script fails, show the user the error instead of guessing.
