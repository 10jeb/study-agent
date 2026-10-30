# Study Agent

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
sample_docs/          Example folder for the agent to work on
  scripts/            Scripts the agent can run with run_script
    recent_files.py   Lists the 5 most recently modified files
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
