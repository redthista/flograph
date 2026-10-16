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
Each outbox entry gains the reply's token count (`usage`) once it is back.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core import ai_disclosure as disc
from ..llm import toolcall, wire
from .tools import CHANGES, PROPOSE, Toolbox, catalogue

DEFAULT_MAX_STEPS = 40
STEP_CHOICES = (20, 40, 80, 150)

SYSTEM_PROMPT = """\
You are the Flo Assistant inside flograph, a visual data-flow app. A flow is \
a graph of nodes: each node has typed inputs and outputs, and settings. Data \
flows along wires from an output to an input; a node runs when its inputs \
have run.

How to work:
- Start with describe_flow to see what is there — or, when the user \
points at nodes, with get_node on those. Nodes are referred to by handles \
such as n1, n2 — use them exactly.
- The node library is listed at the end. Pick from it, and read a type with \
get_node_type before adding it, so you use its real port and setting \
names. Never invent type ids, ports or settings.
- Every node you add must be wired to what feeds it: give add_node \
input_from (e.g. "n3"), which places and wires it in one go. A chart, a \
table or a transform with nothing wired in does nothing. Results tell you \
"unwired_inputs" — wire them before you finish.
- A setting that takes a column needs a real column name. Read it with \
get_output first; if the node has not run, run_nodes runs it.
- Build the smallest change that does what was asked. Never delete, \
replace or rewire the user's existing nodes unless they asked for exactly \
that — to improve a flow, say what you would change and let them agree.
- If the request is unclear — which chart is "this", which column is \
meant — ask one short question instead of guessing. Answering with a \
question is fine.
- Plan before acting: decide the few nodes you need, then add them. Every \
change you make is listed back to you in "this_turn_so_far"; read it and \
never add a node that is already there.
- Feed new nodes from the most processed node that has what they need \
(types already converted, rows already filtered), not from the raw \
reader. Results say when a column is the wrong kind.
- Don't add nodes just to look at data: get_output and run_nodes on the \
existing nodes tell you what is there. If you need values you can't see, \
ask the user.
- A chart compares like with like: don't put measures with different units \
(a weight and a blood test) on one axis — make one chart each.
- Pages show the flow's results to people: a dashboard holds tiles of \
nodes that show something (charts, tables, KPIs…), a report is markdown \
with ![[n3]] embeds, and its look is its CSS: set_report_style for a \
starter theme or the user's saved styles, write_report_css for a look of \
your own. describe_flow lists them (p1, p2…). Build the charts and tables \
first, then make the page from them.
- "A page" is ambiguous inside a report: a separate page (a tab of its \
own), a '# ' section shown on its own in the web layout (set_report_layout, \
one_at_a_time), or a page break when printed. Unless it is clear, ask which \
they mean before making anything. Link pages with [words](page:p2).
- A Report node (flograph.viz.report_card) is markdown on the canvas, in a \
card that can also be a dashboard tile; a report page is a tab of its own. \
When the user asks for a report node, or a write-up on the canvas, add the \
Report node, connect what it should show into its inputs a, b, c and d, then \
set_params its text, embedding with ![[n3]] as on a page — flograph turns \
that into the input n3 is wired to. The card on the canvas shows charts as \
pictures; |live makes them interactive when it is saved as a web page. To describe a flow or a model, read it \
first (describe_flow, then get_node on what matters) and say in plain words \
what it does, where its data comes from, each stage, and what to check.
- A message may start with [On screen: …] — the page the user is looking \
at. "This", "the page" and "its look" mean that page; change the page, not \
the nodes behind it, unless they ask for the charts themselves.
- Prefer library nodes. Write code (write_node_code) only when no node or \
setting does the job, or the user asks: for a new node, add_node \
flograph.scripting.python_script and write its code. write_node_code \
says whether your code is applied at once or waits for the user to read it \
and press Apply; tell the user which.
- If a tool returns an error, read it — it says what is valid — and fix the \
call. Don't repeat a failing call unchanged.
- Each of your replies is one step, and a turn has a limited number of \
them, so ask for several tools in one reply whenever the calls don't depend \
on each other: look up all the node types you need at once, add the nodes \
together, then wire them together.
- When you are done, reply in plain words: what you did, in a few short \
lines, and anything the user should check or set themselves.

{abilities}

What you may see of the data: {level}.
{visibility}"""

_NO_GUESSING = (
    " You cannot see any other values, so never say what a value is or that "
    "you found one. To filter on a category whose values you can't see, ask "
    "the user to set that column to 'Name and values' in Columns… (top of "
    "the Flo panel) — or to tell you the exact value — and stop there. Some "
    "columns may be hidden from you entirely; that is the user's choice.")

_VISIBILITY = {
    disc.STRUCTURE: "You cannot see column names, any values, or text typed "
                    "into settings. Where a setting needs a column, ask the "
                    "user to name it, or leave it for them and say so. "
                    "'<column>' marks a hidden name, '<text, N characters>' "
                    "hidden typed text.",
    disc.SCHEMA: "You can see column names and types, but no values — "
                 "except where a column lists 'values': the user chose to "
                 "share that column's distinct values." + _NO_GUESSING,
    disc.PROFILE: "You can see column names and types, and per column its "
                  "empty share, distinct count, numeric/date range and what it "
                  "looks like — but never the rows themselves. A column that "
                  "lists 'values' is one whose distinct values the user chose "
                  "to share." + _NO_GUESSING,
    disc.FULL: "The user chose to share their data with you: get_output "
               "brings a table's first rows and its category columns' values, "
               "and get_rows reads more. Use the real values — spellings, "
               "ranges, gaps — rather than guessing. Some columns may be "
               "hidden from you; that is the user's choice.",
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
        self._catalogue: Optional[str] = None
        self.outbox: list[dict] = []
        self.messages: list[dict] = [{"role": "system",
                                      "content": self.system_prompt()}]

    def system_prompt(self) -> str:
        level = self.toolbox.disclosure.level
        autonomy = self.toolbox.autonomy
        abilities = ("You can change the flow with add_node, connect, "
                     "set_params, rename_node, disconnect and delete_nodes"
                     + (", and run nodes on this PC with run_nodes"
                        if self.toolbox.runner is not None else "")
                     + ". Each of your turns is one undo step for the user."
                     if autonomy in CHANGES else
                     "You can only look and advise: you cannot change the "
                     "flow. Say what the user should do instead.")
        if autonomy == PROPOSE:
            abilities += (
                " You are proposing: what you add and change shows on the "
                "canvas, faded, until the user keeps or discards it. Nodes "
                "you add don't run until it is kept, so you can't run them "
                "or read their output — build from what the existing nodes "
                "show. When you are done, say what you propose, and that "
                "they can Keep or Discard it below.")
        prompt = SYSTEM_PROMPT.format(abilities=abilities,
                                      level=disc.LEVEL_NAMES[level],
                                      visibility=_VISIBILITY[level])
        if self._catalogue is None:
            self._catalogue = catalogue(self.toolbox.registry)
        # appended, not formatted in: a label may hold braces
        return (prompt + "\n\nThe node library, by category (label = type "
                "id; the 'flograph.' prefix is left off, either form works):\n"
                + self._catalogue)

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
        entry["usage"] = reply.usage
        if reply.mode == "json" and self.tool_mode == "auto":
            self.tool_mode = "json"
        return reply

    def send(self, text: Optional[str], *,
             cancelled: Callable[[], bool] = lambda: False,
             on_event: Optional[Callable[[Event], None]] = None) -> TurnResult:
        """One turn. `text=None` carries on a turn the step limit paused:
        no new message, the model just picks up from its last tool results.
        It is a turn of its own, so it is an undo step of its own."""
        emit = on_event or (lambda event: None)
        result = TurnResult("")

        def open_turn() -> str:
            self.toolbox.begin_turn(text if text is not None else "carry on")
            return self.toolbox.disclosure.scrub(text) if text is not None else ""

        result.sent_text = self._ui(open_turn)
        # the level or the dials may have moved since the last turn
        self.messages[0]["content"] = self.system_prompt()
        if text is not None:
            self.messages.append({"role": "user", "content": result.sent_text})
        checked = False
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
                    missing = ([] if checked
                               or self.toolbox.autonomy not in CHANGES
                               else self._ui(self.toolbox.unwired_added))
                    if not missing:
                        result.text = reply.text
                        break
                    # once per turn: the commonest slip is a node added and
                    # never wired, and the model rarely notices on its own
                    checked = True
                    self.messages.append({"role": "user", "content": (
                        "[Check from flograph, not the user: these nodes you "
                        "added have required inputs with nothing wired in — "
                        + "; ".join(missing) + ". Wire them with connect, or "
                        "if leaving them open is right, say why. Then answer.]")})
                    continue
                stop = cancelled()
                for call in reply.tool_calls:
                    if stop:
                        # every call still gets an answer, or the next
                        # request is malformed in both formats
                        outcome = '{"error": "not run: the user pressed Stop"}'
                    else:
                        emit(Event("tool", call.name))
                        if self.toolbox.runs_off_ui(call):
                            # waits for the engine: on this thread, not the GUI's
                            outcome = self.toolbox.execute_run(call, self._ui,
                                                               cancelled)
                        else:
                            outcome = self._ui(
                                lambda c=call: self.toolbox.execute(c))
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
                "step limit": f"Paused after {self.max_steps} steps so you can "
                              "check how it's going — Continue lets it carry on.",
                "error": f"The AI server failed: {result.error}",
            }[result.stopped] + (f" {done} change(s) so far — one Undo takes "
                                 "them all back." if done else "")
        return result


class _Declined(Exception):
    """before_send said no."""
