"""One conversation with the Flo Assistant (no Qt of its own).

`Conversation.send()` runs one turn: the model answers or asks for tools,
the tools run against the flow, their results go back, and round again
until the model answers in words — or the step limit or Stop ends it.

Every change a turn makes is one undo step (the Toolbox's macro), and
every message that goes out is kept in `outbox` exactly as sent, so "what
left the machine" can be shown, not described.

The user's own words are scrubbed like everything else: an aliased column
typed into the chat must not undo the alias. The conversation remembers
when a server needed the JSON fallback, so it doesn't ask natively and get
refused on every turn after the first.

`send()` blocks on the network, so the UI calls it from a worker thread;
`cancelled` is polled between steps, and `on_event` reports progress.
Everything that touches the flow — opening the turn, every tool, closing
the turn's undo step — goes through `on_ui`, which the dock points at the
GUI thread; undo commands must never be pushed from a worker.
`before_send` sees each request as it is about to go (the send log, and
"confirm every send"); returning False stops the turn without sending.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core import ai_disclosure as disc
from ..llm import toolcall, wire
from ..llm.profiles import level_label
from .tools import ACT, Toolbox

DEFAULT_MAX_STEPS = 16

SYSTEM_PROMPT = """\
You are the Flo Assistant inside flograph, a visual data-flow app. A flow is \
a graph of nodes: each node has typed inputs and outputs, and settings. Data \
flows along wires from an output to an input; a node runs when its inputs \
have run.

How to work:
- Start with describe_flow to see what is there — or, when the user \
points at nodes, with get_node on those. Nodes are referred to by handles \
such as n1, n2 — use them exactly.
- Before adding a node, find its type with find_node_types and read it with \
get_node_type, so you use real type ids, port names and setting names. \
Never invent them.
- Build the smallest flow that does what was asked, wiring each new node to \
the one that feeds it (use 'near' to place it beside that node).
- If a tool returns an error, read it — it says what is valid — and fix the \
call. Don't repeat a failing call unchanged.
- When you are done, reply in plain words: what you did, in a few short \
lines, and anything the user should check or set themselves.

{abilities}

What you may see of the data: {level}.
{visibility}"""

_VISIBILITY = {
    disc.STRUCTURE: "You cannot see column names or any values. Where a "
                    "setting needs a column, ask the user to name it, or leave "
                    "it for them and say so. '<column>' marks a hidden name.",
    disc.SCHEMA: "You can see column names and types, but never any values.",
    disc.PROFILE: "You can see column names and types, and per column its "
                  "empty share, distinct count, numeric/date range and what it "
                  "looks like — but never the rows themselves.",
}


@dataclass
class TurnResult:
    text: str
    actions: list = field(default_factory=list)
    steps: int = 0
    stopped: str = ""   # "" | "cancelled" | "declined" | "step limit" | "error"
    error: str = ""
    sent_text: str = ""        # the user's words as the model got them


@dataclass
class Event:
    kind: str                  # "thinking" | "text" | "tool" | "result"
    name: str = ""
    detail: str = ""


class Conversation:
    def __init__(self, connection: wire.Connection, toolbox: Toolbox, *,
                 tool_mode: str = "auto", max_steps: int = DEFAULT_MAX_STEPS,
                 on_ui: Optional[Callable[[Callable[[], Any]], Any]] = None,
                 before_send: Optional[Callable[[dict], bool]] = None,
                 stream: bool = False):
        self.connection = connection
        self.toolbox = toolbox
        self.tool_mode = tool_mode
        self.max_steps = max_steps
        self._ui = on_ui or (lambda fn: fn())
        self.before_send = before_send
        self.stream = stream
        self.outbox: list[dict] = []
        self.messages: list[dict] = [{"role": "system",
                                      "content": self.system_prompt()}]

    def system_prompt(self) -> str:
        level = self.toolbox.disclosure.level
        abilities = ("You can change the flow with add_node, connect, "
                     "set_params, rename_node, disconnect and delete_nodes. "
                     "Each of your turns is one undo step for the user."
                     if self.toolbox.autonomy == ACT else
                     "You can only look and advise: you cannot change the "
                     "flow. Say what the user should do instead.")
        return SYSTEM_PROMPT.format(abilities=abilities,
                                    level=level_label(level).split(" — ")[0],
                                    visibility=_VISIBILITY[level])

    def _ask(self, emit: Callable[[Event], None] = lambda e: None,
             cancelled: Callable[[], bool] = lambda: False) -> toolcall.Reply:
        tools = self.toolbox.specs()
        entry = {"time": time.time(),
                 "messages": copy.deepcopy(self.messages),
                 "tools": [t.name for t in tools],
                 "mode": self.tool_mode}
        if self.before_send is not None and not self.before_send(entry):
            raise _Declined
        self.outbox.append(entry)
        streaming = ({"on_text": lambda text: emit(Event("text", detail=text)),
                      "cancelled": cancelled} if self.stream else {})
        reply = toolcall.chat_with_tools(self.connection, self.messages,
                                         tools, self.tool_mode, **streaming)
        if reply.mode == "json" and self.tool_mode == "auto":
            self.tool_mode = "json"
        return reply

    def send(self, text: str, *, cancelled: Callable[[], bool] = lambda: False,
             on_event: Optional[Callable[[Event], None]] = None) -> TurnResult:
        emit = on_event or (lambda event: None)
        result = TurnResult("")

        def open_turn() -> str:
            self.toolbox.begin_turn(text)
            return self.toolbox.disclosure.scrub(text)

        result.sent_text = self._ui(open_turn)
        # the level or the dials may have moved since the last turn
        self.messages[0]["content"] = self.system_prompt()
        self.messages.append({"role": "user", "content": result.sent_text})
        try:
            while True:
                if cancelled():
                    result.stopped = "cancelled"
                    break
                if result.steps >= self.max_steps:
                    result.stopped = "step limit"
                    break
                result.steps += 1
                emit(Event("thinking"))
                reply = self._ask(emit, cancelled)
                self.messages.append({
                    "role": "assistant", "content": reply.text,
                    **({"tool_calls": [c.to_dict() for c in reply.tool_calls]}
                       if reply.tool_calls else {})})
                if reply.done:
                    result.text = reply.text
                    break
                stop = cancelled()
                for call in reply.tool_calls:
                    if stop:
                        # every call still gets an answer, or the next
                        # request is malformed in both formats
                        outcome = '{"error": "not run: the user pressed Stop"}'
                    else:
                        emit(Event("tool", call.name))
                        outcome = self._ui(lambda c=call: self.toolbox.execute(c))
                        emit(Event("result", call.name, outcome))
                    self.messages.append({"role": "tool", "tool_call_id": call.id,
                                          "name": call.name, "content": outcome})
                if stop:
                    result.stopped = "cancelled"
                    break
        except wire.LLMError as exc:
            result.stopped, result.error = "error", str(exc)
        except _Declined:
            result.stopped = "declined"
        except wire.Cancelled:
            result.stopped = "cancelled"
        finally:
            self._ui(self.toolbox.end_turn)
            result.actions = list(self.toolbox.actions)
        if result.stopped and not result.text:
            done = len(result.actions)
            result.text = {
                "cancelled": "Stopped.",
                "declined": "Not sent.",
                "step limit": f"Stopped after {self.max_steps} steps without "
                              "finishing.",
                "error": f"The AI server failed: {result.error}",
            }[result.stopped] + (f" {done} change(s) were made — one Undo takes "
                                 "them all back." if done else "")
        return result


class _Declined(Exception):
    """before_send said no."""
