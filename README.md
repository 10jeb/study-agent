# Study Agent

[![Tests](https://github.com/10jeb/study-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/10jeb/study-agent/actions/workflows/tests.yml)

A Python AI agent built on the Anthropic API that reads, searches and runs
scripts over a folder of files, remembers long conversations by summarizing
them, and loads task-specific "skills" on demand, including a DSM-5-TR
study quiz.

## Demo

```text
Agent ready. Asking about files in 'sample_docs'. Type 'quit' to exit.

You: quiz me on disorders
  [context] input tokens this request: 1535
  [tool] load_skill({'name': 'dsm5-study'})
  [context] input tokens this request: 2089
  [tool] load_skill({'name': 'dsm5-study', 'file': 'disorders.json'})
  [context] input tokens this request: 9082

Agent: **DSM-5-TR quiz, question 1**
**Score: 0/0**

Which disorder matches these key features?

- Disinterested in relationships
- Disinterested in sexual experiences
- Takes pleasure in few activities, if any

Name the disorder. You can say "quiz me on personality disorders" or another category if you want to narrow the topics.

You: schizoid disorder, now explain ucb to me as if i were an expert
  [context] input tokens this request: 9374
  [tool] load_skill({'name': 'explain-complexly'})
  [tool] search_files({'word': 'ucb'})
  [context] input tokens this request: 9787
  [tool] read_file({'path': 'study_notes.txt'})
  [context] input tokens this request: 10019

Agent: **Quiz: question 1 result**
Correct. "Schizoid disorder" is schizoid personality disorder, and nothing else in the file has that name. **Score: 1/1.**

I'll hold question 2 until you ask for it.

**Upper-Confidence-Bound (UCB) action selection**

The notes give only a brief statement of UCB. I've filled in the standard formalism (Auer et al.'s UCB1, as presented in Sutton and Barto), which the notes don't contain.

**Setting.** UCB addresses the exploration–exploitation dilemma in the multi-armed bandit problem. The agent must balance exploiting its current value estimates against gathering information to improve them.

**Selection rule.** At time *t*, the agent selects

A_t = argmax_a [ Q_t(a) + c · √( ln t / N_t(a) ) ]

- **Q_t(a)** is the current estimate of the value of action *a*. It is the exploitation term.
- **N_t(a)** is the number of times *a* has been selected so far. The bonus grows as this shrinks.
- **c > 0** sets the degree of exploration.
- **√(ln t / N_t(a))** is the uncertainty term. It is an upper confidence bound on the estimate's deviation from the true mean, derived from a Hoeffding-type concentration inequality. By convention, an action with N_t(a) = 0 is treated as maximizing.

**Principle.** UCB follows optimism in the face of uncertainty. The quantity Q + bonus is a plausible upper bound on an action's true value. An action is selected either because its estimate is high or because its estimate is poorly constrained by data.

**Contrast with ε-greedy, as stated in your notes.**
- ε-greedy explores undirected. With probability ε it samples uniformly, regardless of how much is known about each action. It therefore keeps sampling actions that are clearly inferior.
- UCB explores directed. The bonus is a deterministic function of visitation counts, so exploration targets epistemic uncertainty. As N_t(a) grows, the bonus decays and the policy becomes greedy on its own, without an annealing schedule.
- In the stationary case, UCB attains logarithmic regret, O(ln t). Fixed-ε ε-greedy incurs linear regret.

**Link to the other notes.**
- The bonus depends on N_t(a), which presupposes sample-average-style bookkeeping. That suits stationary problems, as the first paragraph of your notes describes.
- In nonstationary settings, a count-based bonus decays inappropriately. Estimates grow stale while the bonus keeps shrinking, so exploration ceases when it is most needed. Remedies include discounted UCB and sliding-window UCB. These are only partly compatible with constant step-size updates, which the notes recommend for tracking drift.

You: 
```

## Features
- Tool use: list, read and search files; run Python scripts, which must be
  in a `scripts/` folder and stop after 30 seconds
- Context management: trims history and folds dropped turns into a
  running summary
- Skills: SKILL.md folders loaded with progressive disclosure
- Safety limits:
  - File tools resolve every path, including symlinks, and refuse anything
    outside the chosen folder.
  - The agent stops after 15 rounds of tool use per question, so a confused
    model can't loop and run up API cost.
  - Scripts are **not** sandboxed. The path check limits *which* script
    runs, not what it does: a script can read or write any file your user
    account can. Only put scripts you trust in `scripts/`.
- Tested: unit tests with a fake model client run on every push, and a
  benchmark measures how much trimming cuts input tokens

## How it works

The agent runs a loop: it sends the conversation to the model, and if the
model asks to use a tool, the agent runs it, sends back the result, and asks
again, until the model gives a final answer or the loop reaches
`MAX_TOOL_ROUNDS` (15).

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
  explain-complexly/  Explains a topic at an expert level
sample_docs/          Example folder for the agent to work on
  scripts/            Scripts the agent can run with run_script
    recent_files.py   Lists the 5 most recently modified files
tests/                Unit tests that use a fake model client
benchmarks/           Token benchmark for history trimming
.github/workflows/    GitHub Actions: runs the tests on every push
Dockerfile            Runs the agent in a container
.dockerignore         Files kept out of the Docker image
SKILLS.md             How skills work and how to write one
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
Type `quit` to exit. The model, history length and tool-round limit are set
at the top of `agent.py` (`MODEL`, `MAX_HISTORY_TURNS`, `MAX_TOOL_ROUNDS`).

## Run with Docker

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker build -t study-agent .
docker run -it --rm -e ANTHROPIC_API_KEY study-agent
```

`-e ANTHROPIC_API_KEY` passes in the key from your shell, so it is never
stored in the image. To use your own notes, mount the folder read-only and
pass its path in the container:

```bash
docker run -it --rm -e ANTHROPIC_API_KEY -v ~/my-notes:/data:ro study-agent /data
```

In a container, scripts the agent runs can only reach the container's own
files and the folders you mount, and `:ro` stops them from changing your
notes. That limits what a script can touch on your computer, though a
container isn't a complete security boundary: scripts still have network
access, for example.

## Tests

The tests use a fake model client, so they need no API key and make no
network calls.

```bash
python -m unittest discover tests -v
```

They cover the path checks (including symlinks), history trimming and
summarizing, and the cap on tool-use rounds. GitHub Actions runs them on
every push, on the oldest and newest supported Python versions; the badge at
the top of this page shows the latest result.

## Benchmark

`benchmarks/token_benchmark.py` measures what history trimming saves. It
replays the same scripted 30-turn conversation twice, once resending the full
history on every request and once with trimming, and counts the input tokens
of every request the agent would send. The conversation is shaped like real
use: the first turn loads the DSM-5 skill and `disorders.json` (a large tool
result), and later turns quiz and read notes using the real tools and files.

```bash
python benchmarks/token_benchmark.py                 # measured; needs an API key
python benchmarks/token_benchmark.py --turns 50 --csv results.csv
python benchmarks/token_benchmark.py --estimate      # rough, offline, no key
```

It uses Anthropic's token-counting endpoint, which counts a request without
generating a reply. `--real-summary` has the model write the summaries
instead of using a fixed stand-in, which costs a few small model calls.

**Results** (30-turn chat, keeping the last 10 questions, model-written
summaries, measured with the token-counting endpoint):

| | Full history | Trimmed | Saved |
|---|---:|---:|---:|
| All 30 turns | 452,640 | 235,895 | 47.9% |
| Turn 30 alone | 31,968 | 9,136 | 71.4% |

Trimming doesn't make short chats cheaper: the two versions match until the
history passes `MAX_HISTORY_TURNS`. It stops the context from growing without
limit in long ones, where an early large tool result would otherwise be
resent on every later request.

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
