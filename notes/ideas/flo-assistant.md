# Flo Assistant — an assistant that builds the flow with you

**Status:** designed, not started (In-Tray chunk **AH**). **Planned against:**
0.1.30, commit `e9e675c` (2026-10-15). Anything in the codebase may have
moved since.

The ask (Dan, 2026-10-15): a button that opens a modern chat panel on the
right, where you can say *"I've put my data in this Excel reader — make me a
bar chart of revenue by region"* and it does it. It does as much or as
little as you choose, and **you choose how much of your data it sees**:
nothing, the column names, a profile, made-up rows shaped like yours, or the
real thing. It must work against local servers (Ollama, LM Studio) and
online ones (work gateway, Anthropic, OpenAI, OpenRouter), in either the
OpenAI or the Anthropic wire format.

## The two dials

The whole feature hangs on two settings that stay separate in the UI,
because they answer different questions.

### Dial 1 — what it can see (disclosure)

| Level | Sent to the model | Enough for |
|---|---|---|
| **0 Structure** | Node types, wires, params, labels. No column names. | "Put a bar chart after the Excel reader" |
| **1 Schema** | + column names, dtypes, row/column counts | "Bar chart of revenue by region" |
| **2 Profile** | + null %, distinct count, min/max, date range, text length range, inferred kind ("looks like an email"). No values. | Picking the right chart; spotting a date stored as text |
| **3 Look-alike** | + N generated rows that match each column's kind and profile | Writing and testing parsing/regex/format logic |
| **4 Sample** | + first N real rows | Debugging against real data |
| **5 Analyse** | + may run nodes and read their outputs (filtered back through the level-4 rules) | "Why did Q3 drop?" |

**Per-column overrides**, on top of the level:

- **Sensitive** — the column's values never leave the machine at any level.
  It still appears in the schema, so the model can wire it up.
- **Alias** — the column's *name* goes out as `col_7` with a hint you write
  or accept (`col_7: person name`). Tool calls coming back are translated
  from `col_7` to the real name locally, so the flow it builds still says
  `Customer Name`. This is how it can "infer what the data contains without
  seeing it".

**Look-alike rows are generated, not shuffled.** Shuffling each column on
its own is not anonymising it: every real name is still in the payload,
just on another row. Level 3 *generates* values to fit the profile (the
inferred kind plus range, length and null rate). A shuffled-real option, if
it ever exists, is labelled as what it is. The generator is local and
deterministic (seeded per column), so the same flow sends the same rows and
a prompt can be repeated.

**The level is enforced by which tools exist, not by the prompt.** At level
1 the model is simply not given `get_sample`, so a confused model, or an
instruction smuggled in through a cell value, has nothing to call. Every
outgoing payload, including the system prompt's flow summary, is built by
one Qt-free module, `core/ai_disclosure.py`. It is the only place that
reads a cached value on the AI's behalf, and the place the tests pin down.

**The outbox.** Every request can be inspected before or after it goes:
a "what was sent" view per message, an optional *confirm every send*, and
a local append-only log (`<user dir>/ai_log/YYYY-MM-DD.jsonl`) recording
what went where. That makes "show me what left the machine" a question
with an answer.

### Dial 2 — what it can do (autonomy)

- **Advise:** chat and explain only. Graph tools are not offered.
- **Propose:** it plans a change and you see it first: ghost nodes and
  wires on the canvas plus a summary ("adds 3 nodes, 2 wires, changes 1
  param"), with **Accept / Reject**. Accept applies it as one undo step.
- **Act:** it applies changes directly. **Each AI turn is one undo
  macro**, so one Ctrl+Z takes back the whole turn.
- **May run nodes** (tick box, separate): running is always local; what
  comes back to the model is still cut down by Dial 1. At level ≤ 4 a run
  reports only status, row count and schema — enough to know "it worked".

## Connections — local and online, either format

`ai.py` already speaks both wire formats (OpenAI `/chat/completions` with
Bearer, Anthropic `/messages` with `x-api-key`). It handles the 400
parameter climb-down, `/v1` URL shapes, `?api-version=` and `<think>`
blocks. Tools ▸ AI Assistant Settings already stores provider, base URL,
model, key and verify-SSL. The Flo Assistant extends this rather than adding a
second settings screen:

- **Named connection profiles** — e.g. *Local Ollama* and *Work gateway* —
  each with: API format (openai / anthropic), base URL, model, API key or
  token, verify SSL, timeout, max tokens, Thinking, extra request JSON
  (the same escape hatch the LLM Config node has). The existing single
  connection migrates as the first profile. The dock header has a profile
  dropdown.
- **Each profile has a disclosure ceiling.** A profile marked *local* (the
  app can also detect `localhost`/`127.*`/`::1` and suggest it) may allow
  up to level 5 by default. An online profile defaults to a ceiling of 1 and
  must be raised deliberately. Switching from local to online mid-chat
  re-applies the lower ceiling before the next send, and the chat says so.
  This is the "local means nothing leaves the PC" guarantee made visible:
  a **badge** in the dock header reads *Local — nothing leaves this PC* or
  *Online — <host>*.
- **Keys out of QSettings.** Keys are stored in plain QSettings today. A
  security-first feature should keep them in the OS keyring (`keyring`:
  Windows Credential Manager, macOS Keychain, Secret Service). Fall back to
  QSettings with a warning where no keyring exists. Same rule as
  index sign-in: a secret never goes on a command line.
- **Tool calling in both formats.** Added to `ai.py`: OpenAI `tools` /
  `tool_calls` / `role: tool`, and Anthropic `tools` / `tool_use` /
  `tool_result` content blocks. Both map onto one internal shape so the
  agent loop doesn't care which format is in use. Local models vary, so
  there is a **fallback protocol**: the tool list goes into the system
  prompt, the model answers with one fenced JSON action, and the same parser
  that already digs fenced blocks out of chatty replies reads it. A profile
  has *Native tools: auto / on / off*. Auto tries native once and drops to
  the fallback if the server rejects `tools`, the same way the 400 climb-down
  already works.
- **Streaming** for the chat text (SSE in both formats), so a slow local
  model visibly does something. Tool calls are applied once complete,
  never half-parsed.
- `ai.py` and `nodes/ai/_llm.py` already drift (see memory). The Flo Assistant
  goes in `ai.py`. Pulling the shared wire code into one Qt-free module both
  can use is worth doing as phase 0, or the drift becomes three-way.

## The tools the model gets

Offered per turn according to both dials.

**Read** (any level ≥ 0, data shown according to level):
- `describe_flow(scope?)` — nodes, wires, frames, canvases; a frame or the
  current selection can be the scope so big flows stay small.
- `list_node_types(query)` / `get_node_spec(type_id)` — the real catalogue
  from the registry (labels, ports, PARAMS with defaults and choices,
  `suggest` hints), so it uses nodes that exist instead of inventing them.
- `get_schema(node, port)` (≥1), `get_profile(node, port)` (≥2),
  `get_lookalike(node, port, n)` (≥3), `get_sample(node, port, n)` (≥4).

**Write** (Propose/Act only), each one a QUndoCommand that already exists:
- `add_node(type_id, params, near?)`, `connect(src, out, dst, in)`,
  `set_param(node, name, value)`, `delete(ids)`, `add_frame(ids, title)`,
  `add_order_edge(a, b)`.
- `write_user_node(code)` — a new `user.*` node, checked by `parse_spec`
  before it is accepted (the Ask AI path already does this check).
- Layout is **not** the model's job: new nodes are placed by the same
  layout rules the flograph-flow skill uses, relative to `near`.

**Run** (tick box): `run_node(node)` returns status, timing, and the output
cut down by Dial 1.

Each tool's result says what it hid ("3 sensitive columns withheld"), so
the model can say "I can't see that column" instead of guessing.

## The panel

- A right-hand dock, like the Navigator, opened from a title-bar button and
  a shortcut. It stays closed by default.
- Header: profile dropdown + local/online badge, the two dials, a
  per-column privacy button that opens a grid of every column the flow
  knows about with its Sensitive and Alias settings.
- Chat thread with Markdown. AI actions show as small cards
  (*Added Bar Chart ← Excel Reader · view · undo*); clicking a node name
  goes to it (reuse Find Node's cross-canvas jump).
- **Attach**: drag a node or frame onto the input, or "add selection", so
  "this" means something exact.
- Each message has a *what was sent* expander.
- Conversations are saved with the flow. The privacy settings (level,
  per-column flags, ceiling) are saved in the flow too: a flow handed to
  a colleague keeps "this one is schema-only" as its ceiling, and a
  receiving app can only lower it.

## Phases

0. **Shared wire module + keyring.** Unify `ai.py`/`_llm.py` transport;
   connection profiles; keys in the keyring. Small–medium.
1. **Engine, headless.** Tool calling in both formats + fallback;
   `core/ai_disclosure.py` (levels 0–2, Sensitive, Alias); tool → command
   adapter; agent loop with a turn limit and Stop. All testable without Qt
   against a scripted fake model. Medium.
2. **Dock, Advise + Act.** Chat UI, streaming, action cards, one undo macro
   per turn, outbox + log. **First release: levels 0–2, Advise and Act.**
   This covers the "make me a bar chart of X from my Excel reader" case
   without sending a single value.
3. **Propose.** Ghost-node preview + Accept/Reject. Medium. The preview
   needs a scratch graph the commands can be replayed into.
4. **Levels 3–5.** Look-alike generator, real samples, run-and-read. Gated
   behind the outbox having been used, and behind the per-profile ceiling.
5. **Later:** the Flo Assistant editing report pages and dashboards (pages are
   graph state with commands too); "explain this flow" as a report page.

## Decisions taken / still open

- **Taken (2026-10-15):** both local and online servers, configurable API
  format (openai/anthropic), base URL, model and token per connection.
  Privacy settings live in the flow (a receiver can only lower them).
  Build phase 0, then stop for Dan to test. It must work against local
  servers, the work gateway, Anthropic/OpenAI direct *and* OpenRouter — so
  phase 1 needs native tool calling in both formats *and* the JSON
  fallback, not one or the other. No org-level cap for now.
- **Assumed, to confirm:** real values (levels 4–5) wait for phase 4; first
  release is Advise + Act, Propose follows.
- **Phase 0 built (2026-10-15, branch `worktree-ai-copilot-design`):**
  `flograph/llm/` — `wire.py` (the one HTTP implementation; `ai.py` and
  `nodes/ai/_llm.py` both call it, on httpx), `profiles.py` (named
  connections, `ai_profiles.json` in the user folder, location + ceiling),
  `keys.py` (system keychain via `keyring`, owner-only file fallback that
  says so). Tools ▸ AI Assistant Settings edits the profiles; the old
  QSettings connection migrates on first read and its key moves to the
  keychain. Behaviour change: a host-rooted Base URL now tries `/v1` first.
- **Open:**
  - An org-level lock (an admin file that caps the level for every flow
    on a machine) — not now; revisit for the work rollout.
  - Is the ghost-node preview worth its cost, given one-undo-per-turn
    already exists?
  - The turn limit, and whether a long multi-step build stops to check in
    halfway.
  - Whether to show token counts / cost per profile (only meaningful
    online).

## Risks

- **Prompt injection through data.** At level ≥ 3 cell text reaches the
  model. The defence is the dial design itself: what the model *can do* is
  limited by tools and by undo, not by trusting what it reads. No tool
  writes files, sends email or runs arbitrary code outside a node; a
  `write_user_node` is shown to you before anything runs it.
- **Weak local models.** Small models misuse tools. The catalogue lookup
  plus `parse_spec`/registry validation of every tool call (unknown type
  id, wrong port name or bad param value are refused with a reason the
  model can act on) keeps a bad call from becoming a broken graph.
- **Big flows.** `describe_flow` must summarise, not dump. Scope to a
  frame or selection, and page through the rest on request.
