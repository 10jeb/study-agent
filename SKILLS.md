# Step 4: Reusable skills

## What a skill is

A skill is a folder of instructions an agent loads only when a task calls for
it. You've been writing instructions in `SYSTEM_PROMPT`, but everything there
is sent with every request. Ten detailed task guides in the system prompt
would mean paying for all ten on every message, and the model would have to
sort through them each time.

Skills fix that with **progressive disclosure**, which loads instructions in
three levels:

| Level | What | When it's loaded | Cost |
|---|---|---|---|
| 1 | Name + description | Always, in the system prompt | One line per skill |
| 2 | The rest of `SKILL.md` | When the model calls `load_skill` | Only when used |
| 3 | Extra files and scripts | When `SKILL.md` says to read or run them | Only when needed |

This is the same basic format Anthropic uses for Agent Skills, so what you
learn here carries over.

## The format

```
skills/
  study-quiz/
    SKILL.md              <- required: header + instructions
    question_styles.md    <- optional reference (level 3)
  folder-stats/
    SKILL.md
    scripts/
      folder_stats.py     <- optional script (level 3)
```

`SKILL.md` starts with a header between `---` lines:

```markdown
---
name: folder-stats
description: Report how many files, lines and words are in the user's folder. Use when the user asks how big their notes are...
---

# Folder stats
(instructions)
```

Keep the `name` the same as the folder name. The **description** is the most
important line you'll write. It's all the model sees when deciding whether to
load the skill, so say what the skill does AND when to use it.

## How this agent does it

In `agent.py`, look at the "Skills" section:

- `skills_index()` builds the level-1 list and adds it to the system prompt.
- `load_skill(name, file)` is a new tool that returns `SKILL.md` (level 2) or
  another file in the skill (level 3).
- `run_script(name, skill=...)` now runs scripts bundled with a skill, and
  passes your folder path as the script's first argument.

## Try it

```bash
python agent.py sample_docs
```

- "Quiz me on my reinforcement learning notes." Watch the order of the
  `[tool]` lines: first `load_skill(study-quiz)`, then
  `question_styles.md`, then the notes.
- "How much have I written?" It should load `folder-stats`, then run the
  script, instead of guessing the counts.
- "What's on my to-do list?" No skill matches, so none should load.

`MAX_HISTORY_TURNS` is back to 10, since a 5-question quiz needs to remember
more than 2 turns.

## Two kinds of skill

- **study-quiz** is all instructions. It teaches the model a procedure:
  one question at a time, keep score, review at the end.
- **folder-stats** pairs instructions with a script. Use a script for work
  that must be exact (counting, math, parsing, file conversion), where a
  model guessing would be wrong.
