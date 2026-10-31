"""Tests for agent.py that use a fake model client: no API key, no network.

Run from the project folder:
    python -m unittest discover tests -v

What's covered:
  - FileTools._safe_path: the path check that keeps file tools inside the folder
  - trim_history: dropping old turns, summarizing them, and keeping the
    history valid for the API
  - ask(): the MAX_TOOL_ROUNDS cap on the agent loop
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Make `import agent` work no matter where the tests are run from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402


# ---------------------------------------------------------------------------
# A fake model client
#
# The real client's call is client.messages.create(**kwargs) -> response.
# The fake has the same shape, but returns replies scripted by the test and
# records every request so tests can check what the agent sent.
# ---------------------------------------------------------------------------
def text_reply(text):
    """A response where the model answers with plain text (loop ends)."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=0),
    )


def tool_reply(name, tool_input, tool_id):
    """A response where the model asks to use a tool (loop continues)."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=0),
    )


class FakeClient:
    """Returns scripted replies in order; `replies` can also be a function
    that builds a reply from the request (for a model that never stops)."""

    def __init__(self, replies):
        self.replies = replies
        self.requests = []
        self.messages = self   # so client.messages.create(...) works

    def create(self, **kwargs):
        # ask() passes its history list and keeps appending to it, so store
        # a copy of the messages as they were at the time of this request.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        if callable(self.replies):
            return self.replies(len(self.requests))
        if not self.replies:
            raise AssertionError("FakeClient ran out of scripted replies")
        return self.replies.pop(0)


def silent():
    """ask() and trim_history() print progress; keep test output clean."""
    return mock.patch("builtins.print")


# ---------------------------------------------------------------------------
# _safe_path
# ---------------------------------------------------------------------------
class SafePathTests(unittest.TestCase):
    def setUp(self):
        # Layout:  tmp/docs/notes.txt, tmp/docs/sub/deep.txt,
        #          tmp/secret.txt (outside), tmp/docs-private/x.txt (sibling)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.docs = self.tmp / "docs"
        (self.docs / "sub").mkdir(parents=True)
        (self.docs / "notes.txt").write_text("hello\n")
        (self.docs / "sub" / "deep.txt").write_text("deep\n")
        (self.tmp / "secret.txt").write_text("SECRET_KEY=abc123\n")
        (self.tmp / "docs-private").mkdir()
        (self.tmp / "docs-private" / "x.txt").write_text("private\n")
        self.tools = agent.FileTools(str(self.docs))

    def tearDown(self):
        self._tmp.cleanup()

    def symlink_or_skip(self, link, target):
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not supported here (e.g. Windows without admin)")

    def test_allows_file_in_folder(self):
        self.assertEqual(self.tools._safe_path("notes.txt"), self.docs / "notes.txt")

    def test_allows_nested_file(self):
        self.assertEqual(self.tools._safe_path("sub/deep.txt"), self.docs / "sub" / "deep.txt")

    def test_allows_dotdot_that_stays_inside(self):
        # "sub/.." goes down and back up, ending inside the folder.
        self.assertEqual(self.tools._safe_path("sub/../notes.txt"), self.docs / "notes.txt")

    def test_blocks_parent_directory(self):
        with self.assertRaises(ValueError):
            self.tools._safe_path("../secret.txt")

    def test_blocks_deep_escape(self):
        with self.assertRaises(ValueError):
            self.tools._safe_path("sub/../../secret.txt")

    def test_blocks_absolute_path(self):
        # Joining an absolute path replaces the folder entirely:
        # Path("docs") / "/etc/passwd" == Path("/etc/passwd")
        with self.assertRaises(ValueError):
            self.tools._safe_path(str(self.tmp / "secret.txt"))

    def test_blocks_sibling_folder_with_shared_prefix(self):
        # "/tmp/docs-private" starts with the string "/tmp/docs", so a naive
        # str.startswith() check would allow it. is_relative_to() doesn't.
        with self.assertRaises(ValueError):
            self.tools._safe_path("../docs-private/x.txt")

    def test_blocks_symlink_pointing_outside(self):
        self.symlink_or_skip(self.docs / "innocent.txt", self.tmp / "secret.txt")
        with self.assertRaises(ValueError):
            self.tools._safe_path("innocent.txt")

    def test_allows_symlink_pointing_inside(self):
        self.symlink_or_skip(self.docs / "alias.txt", self.docs / "notes.txt")
        self.assertEqual(self.tools._safe_path("alias.txt"), self.docs / "notes.txt")

    def test_search_does_not_leak_symlinked_file(self):
        # Regression test: search_files used to read symlinks without the check.
        self.symlink_or_skip(self.docs / "innocent.txt", self.tmp / "secret.txt")
        result = self.tools.search_files("SECRET")
        self.assertNotIn("abc123", result)
        self.assertNotIn("innocent.txt", self.tools.list_files())


# ---------------------------------------------------------------------------
# trim_history
# ---------------------------------------------------------------------------
def make_turn(i, with_tool=False):
    """One question-and-answer exchange, shaped like real API history.

    Assistant messages include a thinking block, as real replies can.
    with_tool=True adds a tool_use / tool_result pair in the middle.
    """
    thinking = {"type": "thinking", "thinking": "...", "signature": f"sig{i}"}
    msgs = [{"role": "user", "content": f"question {i}"}]
    if with_tool:
        msgs.append({"role": "assistant", "content": [
            thinking, {"type": "tool_use", "id": f"tu{i}", "name": "list_files", "input": {}}]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tu{i}", "content": "notes.txt"}]})
    msgs.append({"role": "assistant", "content": [
        dict(thinking), {"type": "text", "text": f"answer {i}"}]})
    return msgs


def make_history(n, with_tool=False):
    return [m for i in range(1, n + 1) for m in make_turn(i, with_tool)]


class TrimHistoryTests(unittest.TestCase):
    def setUp(self):
        # Small limit so tests stay short. patch.object restores it afterward.
        patcher = mock.patch.object(agent, "MAX_HISTORY_TURNS", 2)
        patcher.start()
        self.addCleanup(patcher.stop)

    def summarizer(self, text="SUMMARY"):
        return FakeClient([text_reply(text)])

    def test_under_limit_returns_history_unchanged_and_calls_no_model(self):
        history = make_history(2)
        client = FakeClient([])          # raises if called
        kept, summary = agent.trim_history(client, history, "old summary")
        self.assertIs(kept, history)
        self.assertEqual(summary, "old summary")
        self.assertEqual(client.requests, [])

    def test_keeps_only_the_last_n_questions(self):
        client = self.summarizer()
        with silent():
            kept, _ = agent.trim_history(client, make_history(4), "")
        questions = [m["content"] for m in kept
                     if m["role"] == "user" and isinstance(m["content"], str)]
        self.assertEqual(questions, ["question 3", "question 4"])

    def test_kept_history_starts_with_a_user_question(self):
        client = self.summarizer()
        with silent():
            kept, _ = agent.trim_history(client, make_history(4, with_tool=True), "")
        self.assertEqual(kept[0]["role"], "user")
        self.assertIsInstance(kept[0]["content"], str)

    def test_summarizes_only_the_dropped_messages(self):
        client = self.summarizer("NEW SUMMARY")
        with silent():
            _, summary = agent.trim_history(client, make_history(4), "")
        self.assertEqual(summary, "NEW SUMMARY")
        sent = client.requests[0]["messages"][0]["content"]
        self.assertIn("question 1", sent)
        self.assertIn("question 2", sent)
        self.assertNotIn("question 3", sent)   # still kept in full, so not summarized

    def test_merges_previous_summary(self):
        client = self.summarizer()
        with silent():
            agent.trim_history(client, make_history(4), "User likes blue.")
        request = client.requests[0]
        self.assertIn("User likes blue.", request["messages"][0]["content"])
        self.assertEqual(request["system"], agent.SUMMARY_INSTRUCTIONS)
        self.assertNotIn("tools", request)     # summarizing must not offer tools

    def test_never_separates_tool_use_from_its_result(self):
        client = self.summarizer()
        with silent():
            kept, _ = agent.trim_history(client, make_history(4, with_tool=True), "")
        requested = set()
        for m in kept:
            if not isinstance(m["content"], list):
                continue
            for block in m["content"]:
                kind = agent._block_type(block)
                if kind == "tool_use":
                    requested.add(agent._field(block, "id"))
                elif kind == "tool_result":
                    self.assertIn(agent._field(block, "tool_use_id"), requested,
                                  "tool_result kept without the tool_use before it")

    def test_strips_thinking_blocks_from_kept_messages(self):
        client = self.summarizer()
        with silent():
            kept, _ = agent.trim_history(client, make_history(4, with_tool=True), "")
        kinds = [agent._block_type(b) for m in kept
                 if isinstance(m["content"], list) for b in m["content"]]
        self.assertNotIn("thinking", kinds)
        self.assertIn("text", kinds)            # real content is still there

    def test_handles_sdk_style_blocks(self):
        # Replies stored from the real API are objects, not dicts.
        history = make_history(2)
        history += [
            {"role": "user", "content": "question 3"},
            {"role": "assistant", "content": [
                SimpleNamespace(type="thinking", thinking="...", signature="s"),
                SimpleNamespace(type="text", text="answer 3")]},
        ]
        client = self.summarizer()
        with silent():
            kept, _ = agent.trim_history(client, history, "")
        kinds = [agent._block_type(b) for b in kept[-1]["content"]]
        self.assertEqual(kinds, ["text"])


# ---------------------------------------------------------------------------
# The agent loop and MAX_TOOL_ROUNDS
# ---------------------------------------------------------------------------
class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        Path(self._tmp.name, "notes.txt").write_text("UCB adds an exploration bonus\n")
        self.tools = agent.FileTools(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assert_valid_history(self, history):
        """The API needs user/assistant turns to alternate."""
        roles = [m["role"] for m in history]
        for a, b in zip(roles, roles[1:]):
            self.assertNotEqual(a, b, f"two '{a}' messages in a row: {roles}")

    def test_returns_text_answer_after_using_a_tool(self):
        client = FakeClient([
            tool_reply("read_file", {"path": "notes.txt"}, "t1"),
            text_reply("UCB adds a bonus."),
        ])
        history = []
        with silent():
            answer = agent.ask(client, self.tools, history, "what is UCB?")
        self.assertEqual(answer, "UCB adds a bonus.")
        self.assertEqual(len(client.requests), 2)
        # The second request carried the tool's real output back to the model.
        result = client.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(result["tool_use_id"], "t1")
        self.assertIn("exploration bonus", result["content"])
        self.assertFalse(result["is_error"])

    def test_tool_error_is_reported_to_model_not_raised(self):
        client = FakeClient([
            tool_reply("read_file", {"path": "missing.txt"}, "t1"),
            text_reply("That file doesn't exist."),
        ])
        with silent():
            answer = agent.ask(client, self.tools, [], "read missing.txt")
        self.assertEqual(answer, "That file doesn't exist.")
        result = client.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])

    def test_stops_a_model_that_never_stops_asking_for_tools(self):
        endless = FakeClient(lambda n: tool_reply("list_files", {}, f"t{n}"))
        history = []
        with silent():
            answer = agent.ask(endless, self.tools, history, "loop forever")
        self.assertEqual(len(endless.requests), agent.MAX_TOOL_ROUNDS)
        self.assertTrue(answer.startswith("Error: stopped after"))
        self.assertEqual(history[-1]["role"], "assistant")
        self.assert_valid_history(history)

    def test_cap_follows_the_setting(self):
        endless = FakeClient(lambda n: tool_reply("list_files", {}, f"t{n}"))
        with mock.patch.object(agent, "MAX_TOOL_ROUNDS", 3), silent():
            agent.ask(endless, self.tools, [], "loop forever")
        self.assertEqual(len(endless.requests), 3)

    def test_conversation_continues_after_hitting_the_cap(self):
        history = []
        endless = FakeClient(lambda n: tool_reply("list_files", {}, f"t{n}"))
        with mock.patch.object(agent, "MAX_TOOL_ROUNDS", 2), silent():
            agent.ask(endless, self.tools, history, "loop forever")
            answer = agent.ask(FakeClient([text_reply("ok")]), self.tools, history, "hello?")
        self.assertEqual(answer, "ok")
        self.assert_valid_history(history)


if __name__ == "__main__":
    unittest.main()
