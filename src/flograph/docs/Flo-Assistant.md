# Flo Assistant

The Flo Assistant is a chat beside the canvas that can read your flow and
change it. Ask for *"a bar chart of sales by region from my Excel reader"*
and it finds the right nodes, adds them, wires them up and sets their
options, and then tells you what it did.

Privacy comes first: the panel always shows where your words go, every
reply ends with a receipt of what left, and nothing is sent until you
press Enter.

Open it with **Tools ▸ Flo Assistant**, **Ctrl+Shift+A**, or the **Flo**
button on the title bar. It needs a connection first: see **Tools ▸ AI
Assistant Settings**, which works with a local server (Ollama, LM Studio,
llama.cpp) or an online one (a work gateway, Anthropic, OpenAI,
OpenRouter), in either the OpenAI or the Anthropic API format.

## The privacy card

Under the connection name (top left — click it to switch) sits a card
that always says where your words go and what the AI sees:
**Local — nothing leaves this PC** in green, or **Online — sent to
*host*** in amber. Switching to a different connection starts a fresh
chat, so nothing the last server was shown goes to the new one.

The first time you send to an online server, Flo asks first and lists
exactly what that server will see and what it never will. Tick *Don't ask
again for this connection* to stop it asking; it asks again if you later
let it see more.

The card carries the two dials:

- **Sees** — how much of your data it is told about:
  - **Structure** — the flow only: node types, wires and settings. Column
    names are replaced with `<column>` everywhere, even in what you type.
  - **Schema** — column names and types too. No rows.
  - **Profile** — also, per column, how much of it is empty, how many
    distinct values it has, its numeric or date range, and what it looks
    like (emails, IDs, a few categories). Never the rows themselves.
- **Can** — **Advise** lets it look and explain but not change anything;
  **Act** lets it add, wire, set, rename and delete nodes.
- **Privacy…** — this flow's own limit, a rule per column, and hiding
  text typed into settings (below).

*Sees* can never go above the lowest of two limits: the connection's
(set per connection in AI Assistant Settings — an online one starts at
Schema) and the flow's own. Lowering it starts a fresh chat, because every
request repeats the conversation so far, and that holds what the higher
level let through.

The limit is enforced by what the AI is *able* to ask for, not by asking it
nicely: at Structure it is not given the tool that reads columns at all.

## Privacy for this flow

**Privacy…** sets the most this flow lets the AI see, whatever the
connection allows.

**Hide text typed into settings.** Node settings go to the AI as written,
so a filter like `customer == "Jane Smith"` sends Jane's name — at every
level, even Structure. Tick this and typed text goes as
`<text, 22 characters>` instead (a setting that is just a column name
still follows the column rules). The AI can still set such settings; it
just can't read what is in them.

It also lists every column the flow has in hand (run the flow first,
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

## Ask Flo about a node or a frame

Right-click a node, a selection of nodes, or a frame and choose **Ask
Flo**:

- **Ask About This…** opens the chat with them attached — an *About* chip
  above the box — so "this" in your message means exactly those nodes.
  Click **×** on the chip to send without it.
- **Explain This**, **Add a Chart From This** and **Suggest a Next Step**
  send that request straight away.
- **Why Did It Fail?** appears when one of them has failed. Error messages
  often quote the data they choked on, so quoted values in an error go to
  the AI as `'<value>'`; column names in it follow the usual rules.

## Changes and undo

Each reply is **one undo step**, however many nodes it touched. The changes
are listed under the reply, each with a **show** link that takes you to the
node, and **Undo these changes** takes the whole reply back (or use
**Ctrl+Z**). Anything you change on the canvas while a reply is still
running joins that reply's undo step.

A big build takes many steps — each look-up and change is a request to the
AI. A reply pauses after 40 (**⋯ ▸ Steps per Reply** sets 20 to 150) so
you can check how it is going; **Continue** under it carries on where it
stopped, as an undo step of its own.

Replies appear as they are written. **Stop** ends a reply mid-sentence,
and nothing the AI asked for in that unfinished answer is done.

## The receipt

Every reply ends with a line saying what it sent and where — for example
*Sent to ai.example.com: your message, the flow (3 nodes), 6 column
names, no rows.* **details** lists the column names, which ones went under
an alias, which had their ranges sent, and whether typed setting text was
included. The receipt is read back from the requests that actually went,
not worked out from the dials, so it reports what left rather than what
should have.

At **Profile**, the smallest and largest value of number and date columns
are real values from your data; the receipt names those columns. Mark a
column *Sensitive* to keep them back.

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
code — those come later, behind the same dials. Chats are not saved in the
flow: a flow you send someone never carries your conversation.
