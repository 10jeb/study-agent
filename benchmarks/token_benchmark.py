"""Measure how much history trimming reduces input tokens in a long chat.

Replays the same scripted conversation two ways and counts the input tokens
of every request the agent would send:

  full     the whole history is resent on every request (no trimming)
  trimmed  agent.trim_history() keeps the last MAX_HISTORY_TURNS questions
           and folds older turns into a short summary

The conversation is shaped like real use of this agent: turn 1 loads the
dsm5-study skill and disorders.json (one large tool result), then it's a
DSM-5 quiz, with study_notes.txt read every 5th turn. Tool results come from
the real tools and files, so their sizes are real. Each tool round counts as
its own request, as it does in agent.ask().

Usage, from the project folder with the venv active:

    python benchmarks/token_benchmark.py                  # 30 turns, measured
    python benchmarks/token_benchmark.py --turns 50
    python benchmarks/token_benchmark.py --real-summary   # model writes summaries
    python benchmarks/token_benchmark.py --csv results.csv
    python benchmarks/token_benchmark.py --estimate       # no API key; rough

Cost: by default this only calls the token-counting endpoint
(client.messages.count_tokens), which counts a request's tokens without
generating a reply; check Anthropic's pricing page for its current cost.
--real-summary also makes one small model call each time history is trimmed.
"""
import argparse
import contextlib
import csv
import io
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import agent  # noqa: E402

# A realistic 4-sentence summary, used unless --real-summary is set, so the
# default run needs no model calls. Real summaries are capped at 5 sentences.
STAND_IN_SUMMARY = (
    "The user is studying DSM-5-TR disorders with the dsm5-study quiz skill, "
    "which loaded disorders.json. The user has answered every quiz question so "
    "far correctly, and the running score is shown after each answer. The user "
    "also asked for explanations of UCB action selection, which came from "
    "study_notes.txt. The user wants one question at a time with the score shown."
)

UCB_EXPLANATION = (
    "**UCB, briefly.** Upper-Confidence-Bound action selection picks the action "
    "with the highest estimated value plus an exploration bonus, "
    "c * sqrt(ln t / N_t(a)). The bonus is large for actions tried only a few "
    "times and shrinks as N_t(a) grows, so exploration is directed at the "
    "actions the agent is least sure about, unlike epsilon-greedy, which "
    "explores at random. Your notes contrast this with sample-average and "
    "constant step-size updates: UCB's count-based bonus suits stationary "
    "problems, while drifting problems need a discounted or sliding-window "
    "variant."
)


class StandInSummarizer:
    """Stands in for the model when trim_history() asks for a summary."""

    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=STAND_IN_SUMMARY)])


# ---------------------------------------------------------------------------
# The scripted conversation
# ---------------------------------------------------------------------------
def load_disorders() -> list[tuple[str, str]]:
    path = agent.SKILLS_DIR / "dsm5-study" / "disorders.json"
    if not path.is_file():
        sys.exit(f"Needs {path.relative_to(ROOT)}, which the scripted quiz is built from.")
    return list(json.loads(path.read_text(encoding="utf-8")).items())


def quiz_text(t: int, previous: str | None, symptoms: str) -> str:
    parts = []
    if previous:
        parts.append(
            f'**Question {t - 1} result:** Correct. "{previous}" matches those '
            f"features. **Score: {t - 1}/{t - 1}.**"
        )
    parts.append(f"**DSM-5-TR quiz, question {t}**\n\nWhich disorder matches these key features?")
    features = [s.strip() for s in symptoms.replace(";", ",").split(",") if s.strip()]
    parts.append("\n".join(f"- {s}" for s in features))
    parts.append("Name the disorder, or ask me to narrow the quiz to a category.")
    return "\n\n".join(parts)


def build_turn(t: int, disorders, tools: agent.FileTools) -> list[dict]:
    """All messages for turn t: the question, any tool rounds, the reply."""
    previous = disorders[(t - 2) % len(disorders)][0] if t > 1 else None
    _, symptoms = disorders[(t - 1) % len(disorders)]

    if t == 1:
        question = "quiz me on disorders"
        calls = [("load_skill", {"name": "dsm5-study"}),
                 ("load_skill", {"name": "dsm5-study", "file": "disorders.json"})]
        reply = quiz_text(t, None, symptoms)
    elif t % 5 == 0:
        question = f"{previous}. also, remind me how UCB works"
        calls = [("read_file", {"path": "study_notes.txt"})]
        reply = quiz_text(t, previous, symptoms) + "\n\n" + UCB_EXPLANATION
    else:
        question = previous
        calls = []
        reply = quiz_text(t, previous, symptoms)

    messages = [{"role": "user", "content": question}]
    for i, (name, tool_input) in enumerate(calls):
        tool_id = f"toolu_{t}_{i}"
        messages.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": tools.run(name, tool_input)}]})
    messages.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
    return messages


def request_prefixes(turn: list[dict]) -> list[list[dict]]:
    """The new messages included in each request agent.ask() sends this turn:
    one after the question, then one after each tool result."""
    tool_rounds = (len(turn) - 2) // 2
    return [turn[: 1 + 2 * i] for i in range(tool_rounds + 1)]


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------
def make_counter(estimate: bool):
    if estimate:
        # Rough rule of thumb: about 4 characters per token for English text.
        def count(system: str, messages: list) -> int:
            payload = json.dumps({"system": system, "tools": agent.TOOLS, "messages": messages})
            return len(payload) // 4
        return count

    import anthropic
    client = anthropic.Anthropic()

    def count(system: str, messages: list) -> int:
        for attempt in range(6):
            try:
                result = client.messages.count_tokens(
                    model=agent.MODEL, system=system, tools=agent.TOOLS, messages=messages)
                return result.input_tokens
            except anthropic.RateLimitError:
                time.sleep(2 ** attempt)   # back off: 1, 2, 4, 8... seconds
        sys.exit("Still rate limited after several retries. Try again later or use fewer --turns.")
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--turns", type=int, default=30, help="questions in the chat (default 30)")
    parser.add_argument("--keep", type=int, default=agent.MAX_HISTORY_TURNS,
                        help=f"MAX_HISTORY_TURNS to test (default {agent.MAX_HISTORY_TURNS})")
    parser.add_argument("--real-summary", action="store_true",
                        help="have the model write each summary instead of a fixed stand-in")
    parser.add_argument("--estimate", action="store_true",
                        help="estimate tokens from characters; no API key, not for reporting")
    parser.add_argument("--csv", type=Path, help="also save the per-turn numbers to this CSV file")
    args = parser.parse_args()

    needs_api = not args.estimate or args.real_summary
    if needs_api and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first, or run with --estimate for a rough offline number.")

    agent.MAX_HISTORY_TURNS = args.keep
    count = make_counter(args.estimate)
    if args.real_summary:
        import anthropic
        summarizer = anthropic.Anthropic()
    else:
        summarizer = StandInSummarizer()

    disorders = load_disorders()
    tools = agent.FileTools(str(ROOT / "sample_docs"))

    mode = "ESTIMATE (characters / 4)" if args.estimate else f"measured with count_tokens, model {agent.MODEL}"
    summary_mode = "model-written" if args.real_summary else "fixed stand-in"
    print(f"{args.turns}-turn chat, keeping the last {args.keep} questions; {mode}; "
          f"{summary_mode} summary\n")
    print(f"{'turn':>4}  {'full':>8}  {'trimmed':>8}  {'saved':>6}")

    full, trimmed, summary = [], [], ""
    rows = []
    for t in range(1, args.turns + 1):
        # Same order as agent.main(): trim first, then ask the new question.
        with contextlib.redirect_stdout(io.StringIO()):   # hide trim_history's printing
            trimmed, summary = agent.trim_history(summarizer, trimmed, summary)

        turn = build_turn(t, disorders, tools)
        full_tokens = sum(count(agent.build_system_prompt(""), full + p)
                          for p in request_prefixes(turn))
        trim_tokens = sum(count(agent.build_system_prompt(summary), trimmed + p)
                          for p in request_prefixes(turn))
        saved = 1 - trim_tokens / full_tokens
        rows.append((t, full_tokens, trim_tokens, saved))
        print(f"{t:>4}  {full_tokens:>8,}  {trim_tokens:>8,}  {saved:>6.1%}")

        full = full + turn
        trimmed = trimmed + turn

    total_full = sum(r[1] for r in rows)
    total_trim = sum(r[2] for r in rows)
    last = rows[-1]
    print(f"\nInput tokens over all {args.turns} turns: {total_full:,} full vs "
          f"{total_trim:,} trimmed ({1 - total_trim / total_full:.1%} less)")
    print(f"Turn {last[0]} alone: {last[1]:,} full vs {last[2]:,} trimmed ({last[3]:.1%} less)")

    if args.csv:
        with args.csv.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["turn", "full_tokens", "trimmed_tokens", "saved_fraction"])
            writer.writerows((t, a, b, f"{s:.4f}") for t, a, b, s in rows)
        print(f"Saved per-turn numbers to {args.csv}")

    if args.estimate:
        print("\nThese are rough estimates. Run without --estimate before reporting a number.")


if __name__ == "__main__":
    main()
