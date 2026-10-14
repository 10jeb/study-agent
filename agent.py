"""
agent.py: a minimal AI agent that can read files and remember the conversation.

What this teaches (Phase 1):
  1. Calling a model: every request is STATELESS. The model only knows
     what is inside the `messages` list you send it.
  2. Context management: we keep a `history` list ourselves, resend it
     every turn, and trim it when it grows too long.
  3. Tool use: we describe tools (list_files, read_file) to the model.
     The model ASKS to use them; OUR code runs them and sends results back.
  4. Skills: folders of instructions in skills/. Only each skill's name
     and description go in the system prompt; the model loads the full
     instructions with load_skill when a task calls for them.
     See SKILLS.md.

Run it:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY="sk-ant-..."     # from the Claude Console
    python agent.py sample_docs
"""

import os
import sys
import subprocess
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
MODEL = "claude-sonnet-5-5"   # check docs.claude.com for current model names
MAX_TOKENS = 1024             # max length of each model reply
MAX_HISTORY_TURNS = 10        # how many user questions to keep in memory
MAX_FILE_CHARS = 20_000       # cap on how much of a file we send back

# Skills live next to this file, separate from the user's data folder.
SKILLS_DIR = (Path(__file__).parent / "skills").resolve()

# The system prompt sets standing instructions. It is sent with EVERY
# request but is not part of the message history.
SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions about the files in "
    "the user's folder. Use the list_files tool to see what is available, "
    "read_file to open a file before answering questions about its contents, "
    "search_files to return lines from files that contain a given word, "
    "and run_script to run Python scripts. Users often misspell or "
    "half-remember terms, so if a search finds nothing, don't stop there: "
    "try a shorter fragment or a likely correct spelling, or read the files "
    "most likely to cover the topic. If the files really don't contain the "
    "answer, say so."
)

# Used for the separate summarizing call. It has its own instructions,
# because summarizing is a different job from answering questions.
SUMMARY_INSTRUCTIONS = (
    "You maintain a running memory for a chatbot. Combine the existing summary "
    "with the new transcript into ONE updated summary of at most 5 sentences. "
    "Keep facts the user stated about themselves, their preferences, decisions "
    "made, and what files or tools were used. Describe ONLY what appears in "
    "the transcript: never claim something hasn't happened (like 'no tools "
    "have been used'), because newer messages you can't see may contradict it. "
    "Skip small talk and the assistant's offers to help. Reply with only the "
    "summary."
)

# ---------------------------------------------------------------------------
# Tool definitions: what the MODEL sees.
# Each tool has a name, a description (the model reads this to decide when
# to use it), and a JSON schema describing its inputs.
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "list_files",
        "description": "List all files in the user's folder, with their sizes.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read the text contents of one file in the user's folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the folder, e.g. 'notes.txt'",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        # The model can't see your code, so the description is the only way
        # it knows how the tool behaves. Be specific.
        "description": (
            "Search every file in the user's folder for text. Case-insensitive, "
            "and matches inside longer words ('can' also matches 'scan'), but "
            "spelling must be exact: a misspelled word won't match. Returns "
            "each matching line as file:line_number: text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "word": {
                    "type": "string",
                    "description": "Word parameter given for which to search, e.g. 'run'"
                }
            },
            "required": ["word"],
        },
    },
    {
        "name": "run_script",
        "description": (
            "Run a Python script and return its exit code, output and errors. "
            "By default runs from the user's scripts/ folder; pass `skill` to run "
            "a script bundled with that skill instead. Every script receives the "
            "path of the user's folder as its first argument."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "File name of the script, e.g. 'hello.py'",
                },
                "skill": {
                    "type": "string",
                    "description": "Optional: name of the skill whose scripts/ folder holds the script",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "load_skill",
        "description": (
            "Load a skill's instructions. Call this BEFORE starting any task that "
            "matches a skill listed in your system prompt, then follow what it "
            "says. By default returns SKILL.md; pass `file` to read another file "
            "the instructions point to."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The skill's name, e.g. 'study-quiz'",
                },
                "file": {
                    "type": "string",
                    "description": "Optional: a file inside the skill folder, e.g. 'question_styles.md'",
                },
            },
            "required": ["name"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations: what YOUR code actually does.
# ---------------------------------------------------------------------------
class FileTools:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _safe_path(self, rel_path: str) -> Path:
        """Resolve a path and make sure it stays inside the root folder.

        Never trust a path the model gives you: without this check,
        '../../etc/passwd' would let it read anything on your machine.
        """
        target = (self.root / rel_path).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError(f"'{rel_path}' is outside the allowed folder")
        return target

    def _visible_files(self) -> list[Path]:
        """All files in the folder, skipping hidden ones like macOS's
        .DS_Store, which are noise to the model and not really text."""
        return [
            p for p in sorted(self.root.rglob("*"))
            if p.is_file()
            and not any(part.startswith(".") for part in p.relative_to(self.root).parts)
        ]

    def list_files(self) -> str:
        files = [
            f"{p.relative_to(self.root)} ({p.stat().st_size} bytes)"
            for p in self._visible_files()
        ]
        return "\n".join(files) if files else "(folder is empty)"

    def read_file(self, path: str) -> str:
        target = self._safe_path(path)
        if not target.is_file():
            raise FileNotFoundError(f"No file named '{path}'")
        text = target.read_text(encoding="utf-8", errors="replace")
        # Context management applies to tool results too: a huge file would
        # eat the model's context window, so we cut it off.
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + "\n...[truncated]"
        return text

    def search_files(self, word: str) -> str:
        """Return every line containing `word`, across all files."""
        matches = []
        for p in self._visible_files():
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            for num, line in enumerate(lines, start=1):
                if word.lower() in line.lower():
                    rel = p.relative_to(self.root)
                    matches.append(f"{rel}:{num}: {line.strip()}")
 
        if not matches:
            return f"No lines contain '{word}'."
        result = "\n".join(matches)
        # Context management: a common word could match thousands of lines.
        if len(result) > MAX_FILE_CHARS:
            result = result[:MAX_FILE_CHARS] + "\n...[truncated]"
        return result

    def run_script(self, name: str, skill: str | None = None) -> str:
        if skill:
            # A skill's own scripts live in skills/<skill>/scripts/.
            scripts_dir = (_skill_dir(skill) / "scripts").resolve()
        else:
            scripts_dir = (self.root / "scripts").resolve()
        script_path = (scripts_dir / name).resolve()
        if not script_path.is_relative_to(scripts_dir):
            raise ValueError("Access denied: Scripts must reside within the designated scripts/ folder.")
        if not script_path.is_file():
            raise FileNotFoundError(f"Script '{name}' not found in scripts/.")
        if script_path.suffix != ".py":
            raise ValueError("Only Python (.py) files are allowed to be executed.")
        try:
            result = subprocess.run(
                # sys.executable is the Python running this agent (your venv),
                # which avoids "python" vs "python3" problems on macOS.
                # The user's folder is passed as the first argument, so a
                # skill's script knows which files to work on.
                [sys.executable, str(script_path), str(self.root)],
                capture_output=True,
                text=True,
                timeout=30,          # stop runaway scripts
                cwd=scripts_dir,     # script runs from its own folder
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"'{name}' took longer than 30 seconds and was stopped.")
 
        # Tool results must be TEXT, so format the outcome as a string.
        output = (
            f"exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout or '(none)'}\n"
            f"stderr:\n{result.stderr or '(none)'}"
        )
        if len(output) > MAX_FILE_CHARS:
            output = output[:MAX_FILE_CHARS] + "\n...[truncated]"
        return output

    def run(self, name: str, tool_input: dict) -> str:
        """Dispatch a tool call by name."""
        if name == "list_files":
            return self.list_files()
        if name == "read_file":
            return self.read_file(tool_input["path"])
        if name == "search_files":
            return self.search_files(tool_input["word"])
        if name == "run_script":
            return self.run_script(tool_input["name"], tool_input.get("skill"))
        if name == "load_skill":
            return load_skill(tool_input["name"], tool_input.get("file", "SKILL.md"))
        raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Skills
#
# A skill is a folder: skills/<name>/SKILL.md, plus optional extra files
# (reference docs, scripts/). SKILL.md starts with a header ("frontmatter")
# giving the skill's name and description:
#
#     ---
#     name: study-quiz
#     description: Quiz the user on their notes. Use when ...
#     ---
#     (full instructions follow)
#
# Skills are loaded in three levels, so they cost almost nothing until used:
#   1. Name + description of EVERY skill: always in the system prompt.
#   2. The rest of SKILL.md: only when the model calls load_skill.
#   3. Extra files: only if SKILL.md tells the model to read or run them.
# ---------------------------------------------------------------------------
def read_frontmatter(skill_md: Path) -> dict:
    """Parse the simple `key: value` header between the --- lines."""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    _, header, _ = text.split("---", 2)
    fields = {}
    for line in header.strip().splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def skills_index() -> str:
    """Level 1: one line per skill, added to the system prompt.

    Re-read on every request, so a skill you add appears without restarting.
    """
    entries = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        meta = read_frontmatter(skill_md)
        name = skill_md.parent.name   # the folder name is what load_skill uses
        entries.append(f"- {name}: {meta.get('description', '(no description)')}")
    if not entries:
        return ""
    return (
        "\n\nYou have skills: packaged instructions for specific tasks. Only "
        "their names and descriptions are listed here. When a request matches "
        "a skill, call load_skill with its name BEFORE starting, then follow "
        "the instructions it returns.\n" + "\n".join(entries)
    )


def _skill_dir(name: str) -> Path:
    """Find a skill's folder, refusing names like '../..'."""
    skill_dir = (SKILLS_DIR / name).resolve()
    if not skill_dir.is_relative_to(SKILLS_DIR) or not (skill_dir / "SKILL.md").is_file():
        raise FileNotFoundError(f"No skill named '{name}'.")
    return skill_dir


def load_skill(name: str, file: str = "SKILL.md") -> str:
    """Levels 2 and 3: return a skill's instructions or one of its files."""
    skill_dir = _skill_dir(name)
    target = (skill_dir / file).resolve()
    if not target.is_relative_to(skill_dir) or not target.is_file():
        raise FileNotFoundError(f"Skill '{name}' has no file '{file}'.")
    text = target.read_text(encoding="utf-8", errors="replace")

    if file == "SKILL.md":
        # Mention the other files without loading them (that's level 3).
        others = [
            str(p.relative_to(skill_dir))
            for p in sorted(skill_dir.rglob("*"))
            if p.is_file() and p.name != "SKILL.md"
        ]
        if others:
            text += (
                f"\n\n[Other files in this skill: {', '.join(others)}. "
                "Read or run them only when these instructions say to.]"
            )
    return text


# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------
def trim_history(client, history: list, summary: str) -> tuple[list, str]:
    """Keep only the most recent MAX_HISTORY_TURNS questions, and fold the
    dropped messages into a running summary so their facts aren't lost.

    We cut at the start of a user QUESTION (a user message whose content
    is a plain string). Cutting anywhere else could separate a tool_use
    request from its tool_result, and the API rejects that.

    Returns (kept_messages, updated_summary).
    """
    question_starts = [
        i for i, m in enumerate(history)
        if m["role"] == "user" and isinstance(m["content"], str)
    ]
    if len(question_starts) <= MAX_HISTORY_TURNS:
        return history, summary
    cut = question_starts[-MAX_HISTORY_TURNS]

    # Summarize what we're about to THROW AWAY, not what we're keeping:
    # the kept messages are still sent in full.
    dropped = history[:cut]
    summary = summarize(client, summary, dropped)
    print(f"  [context] dropped {cut} old messages; summary is now:\n    {summary}")

    # Strip thinking blocks: their signatures are tied to the full
    # conversation and become invalid once earlier messages are removed.
    kept = []
    for m in history[cut:]:
        if m["role"] == "assistant" and isinstance(m["content"], list):
            m = {
                "role": "assistant",
                "content": [b for b in m["content"] if _block_type(b) not in THINKING_TYPES],
            }
        kept.append(m)
    return kept, summary


def summarize(client, old_summary: str, dropped: list) -> str:
    """Ask the model to merge the old summary with the dropped messages.

    This is a plain model call, not ask(): no tools, no history, its own
    instructions. Merging (instead of appending) keeps the summary from
    growing forever, which would defeat the point of trimming.
    """
    prompt = (
        f"Existing summary:\n{old_summary or '(none yet)'}\n\n"
        f"New transcript to fold in:\n{messages_to_text(dropped)}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SUMMARY_INSTRUCTIONS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()


def messages_to_text(messages: list) -> str:
    """Turn message dicts into a readable transcript.

    You can't "".join() the history directly: each message is a dict, and
    its content is either a string or a list of blocks (text, tool_use,
    tool_result, thinking). We pull out the readable parts.
    """
    lines = []
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            lines.append(f"{role}: {content}")
            continue
        for b in content:
            kind = _block_type(b)
            if kind == "text":
                lines.append(f"{role}: {_field(b, 'text')}")
            elif kind == "tool_use":
                lines.append(f"assistant used {_field(b, 'name')}({_field(b, 'input')})")
            elif kind == "tool_result":
                # Tool output can be huge (a whole file); a preview is enough.
                lines.append(f"tool result: {str(_field(b, 'content'))[:300]}")
            # thinking blocks are skipped
    return "\n".join(lines)


THINKING_TYPES = {"thinking", "redacted_thinking"}


def _block_type(block) -> str:
    """Content blocks may be SDK objects or plain dicts; handle both."""
    return _field(block, "type") or ""


def _field(block, key: str):
    """Read a field from a block, whether it's a dict or an SDK object."""
    return block.get(key) if isinstance(block, dict) else getattr(block, key, None)


# ---------------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------------
def ask(client, tools: FileTools, history: list, question: str, summary: str = "") -> str:
    """Send a question and keep going until the model gives a final answer."""
    history.append({"role": "user", "content": question})

    # Build the system prompt fresh each time rather than modifying the
    # SYSTEM_PROMPT constant, so the base instructions never change.
    system = SYSTEM_PROMPT + skills_index()
    if summary:
        system += (
            "\n\nOlder messages were removed to save space. "
            f"Summary of the earlier conversation:\n{summary}"
        )

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            messages=history,   # the WHOLE conversation, every time
        )
        # Watching this number grow is the best way to "feel" context.
        print(f"  [context] input tokens this request: {response.usage.input_tokens}")

        # Save the model's reply (text and/or tool requests) to history.
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # No more tools requested: this is the final answer.
            return "".join(b.text for b in response.content if b.type == "text")

        # The model asked for one or more tools. Run each one and send
        # every result back in a single user message.
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  [tool] {block.name}({block.input})")
            try:
                output, is_error = tools.run(block.name, block.input), False
            except Exception as e:
                # Report errors to the model instead of crashing; it can
                # often recover (e.g. by listing files and retrying).
                output, is_error = f"Error: {e}", True
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,   # links this result to the request
                "content": output,
                "is_error": is_error,
            })
        history.append({"role": "user", "content": results})
        # Loop again so the model can use the results.


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "sample_docs"
    if not Path(folder).is_dir():
        sys.exit(f"Folder not found: {folder}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first (get one from the Claude Console).")

    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY automatically
    tools = FileTools(folder)
    history = []                     # our memory of the conversation
    summary = ""                     # facts from messages we've trimmed away

    print(f"Agent ready. Asking about files in '{folder}'. Type 'quit' to exit.\n")
    while True:
        question = input("You: ").strip()
        if question.lower() in {"quit", "exit"}:
            break
        if not question:
            continue
        history, summary = trim_history(client, history, summary)
        answer = ask(client, tools, history, question, summary)
        print(f"\nAgent: {answer}\n")


if __name__ == "__main__":
    main()
