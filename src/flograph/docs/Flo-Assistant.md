# Flo Assistant

The Flo Assistant is a chat beside the canvas that can read your flow and
change it. Ask for *"a bar chart of sales by region from my Excel reader"*
and it finds the right nodes, adds them, wires them up and sets their
options, and then tells you what it did.

Open it with **Tools ▸ Flo Assistant**, **Ctrl+Shift+A**, or the **Flo**
button on the title bar. It needs a connection first: see **Tools ▸ AI
Assistant Settings**, which works with a local server (Ollama, LM Studio,
llama.cpp) or an online one (a work gateway, Anthropic, OpenAI,
OpenRouter), in either the OpenAI or the Anthropic API format.

## The header

- **Connection** — which of your saved connections to use. The badge says
  **Local** (the server is on this PC, so nothing leaves it) or **Online**
  (hover it to see the host). Switching to a different connection starts a
  fresh chat, so nothing the last server was shown goes to the new one.
- **Sees** — how much of your data it is told about:
  - **Structure** — the flow only: node types, wires and settings. Column
    names are replaced with `<column>` everywhere, even in what you type.
  - **Schema** — column names and types too. No values.
  - **Profile** — also, per column, how much of it is empty, how many
    distinct values it has, its numeric or date range, and what it looks
    like (emails, IDs, a few categories). Never the rows themselves.
- **Can** — **Advise** lets it look and explain but not change anything;
  **Act** lets it add, wire, set, rename and delete nodes.
- **Columns…** — this flow's own limit, and a rule per column (below).

*Sees* can never go above the lowest of two limits: the connection's
(set per connection in AI Assistant Settings — an online one starts at
Schema) and the flow's own. Lowering it starts a fresh chat, because every
request repeats the conversation so far, and that holds what the higher
level let through.

The limit is enforced by what the AI is *able* to ask for, not by asking it
nicely: at Structure it is not given the tool that reads columns at all.

## Per-column rules

**Columns…** lists every column the flow has in hand (run the flow first,
so its tables exist) and lets you set, for each one:

- **Sensitive** — send its name and type only: no ranges, counts or
  guesses at what it holds.
- **Shown to the AI as** — an alias. The real name is replaced everywhere
  it is sent, and turned back into the real one in what the AI sends back,
  so it can set a chart's X axis to your `patient_name` column while only
  ever knowing it as `Customer`.
- **Meaning** — a note sent with the alias, standing in for what the real
  name would have told it.

These, and the flow's limit, are saved in the flow. Whoever you send it to
gets the same limit: their connection can lower it but not raise it. It is
a setting rather than a lock, so anyone who edits the flow can change it.

## Changes and undo

Each reply is **one undo step**, however many nodes it touched. The changes
are listed under the reply, each with a **show** link that takes you to the
node, and **Undo these changes** takes the whole reply back (or use
**Ctrl+Z**). Anything you change on the canvas while a reply is still
running joins that reply's undo step.

**Stop** takes effect as soon as the AI next answers: whatever it asked to
do in that answer is not done.

## What was sent

Under every reply, **What was sent** shows the requests behind it, in full:
the instructions, your message as the AI got it (with any hidden or aliased
names), and every tool result. From the **⋯** menu:

- **Confirm Every Send** shows each request before it goes, with **Send**
  and **Don't Send**.
- **Open Send Log Folder** — every request is also written to a log on
  this PC, one file per day (`ai_log` in flograph's user folder), readable
  by you only.

## Not yet

It does not see real rows or run nodes yet, and it cannot write new node
code — those come later, behind the same dials.
