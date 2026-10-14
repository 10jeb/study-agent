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

The agent runs a loop: it sends the conversation to the model, and if the
model asks to use a tool, the agent runs it, sends back the result, and asks
again, until the model gives a final answer.

```
You ask a question
  -> append to history
  -> send history + tool list to the model
  -> model replies with either:
       text (done)              -> print answer
       a tool_use request       -> your code runs the tool
                                -> append tool_result to history
                                -> send again (loop)
```

**Context management.** The model is stateless, so the agent keeps the
conversation history and resends it on every request. When the history grows
past a set number of turns, the oldest turns are removed and folded into a
short running summary in the system prompt, so facts from early in the
conversation aren't lost. Trimming always cuts at the start of a user
question, so a tool request is never separated from its result, and thinking
blocks are stripped from kept messages because their signatures are tied to
the full original conversation.

**Skills.** A skill is a folder in `skills/` containing a `SKILL.md` file:
a short header (name and description) followed by full instructions. Only
the one-line descriptions are always in the system prompt. The model calls
`load_skill` to read a skill's full instructions when a request matches, and
reads reference files or runs bundled scripts only when those instructions
say to. This keeps every request small while still giving the agent detailed
know-how for specific tasks.

## Project structure

```
agent.py              The agent: tool definitions, agent loop, context
                      management, and skill loading
skills/               Reusable skills, one folder each
  study-quiz/         Quizzes you on your notes and keeps score
  folder-stats/       Counts files, lines and words with a script
  find-todos/         Lists unchecked "- [ ]" items across files
  dsm5-study/         DSM-5-TR quiz built on disorders.json
sample_docs/          Example folder for the agent to work on
  scripts/            Scripts the agent can run with run_script
requirements.txt      Python dependencies
```

## Setup

Requires Python 3.10 or newer and an API key from the
[Claude Console](https://console.anthropic.com).

```bash
git clone https://github.com/10jeb/study-agent.git
cd study-agent
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."  # Windows: set ANTHROPIC_API_KEY=sk-ant-...
python agent.py sample_docs
```

To use your own files, pass a different folder: `python agent.py ~/my-notes`.
Type `quit` to exit. The model and history length are set at the top of
`agent.py` (`MODEL`, `MAX_HISTORY_TURNS`).

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
