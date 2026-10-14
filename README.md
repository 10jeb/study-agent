# Study Agent

A Python AI agent built on the Anthropic API that reads, searches and runs
scripts over a folder of files, remembers long conversations by summarizing
them, and loads task-specific "skills" on demand, including a DSM-5-TR
study quiz.

## Demo
(Paste a short, real transcript from your terminal: e.g. "Quiz me on
personality disorders", one question, a loose answer like "OCD", and the
agent's grading. Keep the [tool] lines in; they show the agent working.)

## Features
- Tool use: list, read and search files; run Python scripts in a sandbox
- Context management: trims history and folds dropped turns into a
  running summary
- Skills: SKILL.md folders loaded with progressive disclosure
- Safety: path checks block access outside the folder; scripts time out

## How it works
(The agent loop diagram from the old README, plus 2-3 sentences each on
context management and skills.)

## Project structure
agent.py, skills/, sample_docs/ — one line each on what they hold.

## Setup
(The venv / pip / export / run steps you already have.)

## Lessons learned
- Thinking blocks are cryptographically tied to their conversation;
  trimming history broke them until I stripped them.
- A summarizer only sees what's dropped, so it must never claim
  something "hasn't happened."
- The model can't see your code: a vague tool description made it
  guess wrong about how search worked.
- Exact-match search fails on typos; next step is fuzzy matching or
  embeddings.

## Next steps
Deploying to AWS (S3 for files, Lambda for scripts), embedding-based
search.