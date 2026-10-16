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

## What Flo can see

Two settings decide it, and both are saved in the flow — so a flow you
send someone carries its rules with it.

**Flo can see** (on the panel) — one choice for the whole flow:

- **Nothing from my data** — only the flow's layout: which nodes, how they
  are wired, their settings. No column names (they go as `<column>`, even
  in what you type) and no text typed into settings.
- **Column names** — the default. Also column names and types, and
  settings as you typed them (a filter's values too).
- **Column names and summaries** — also, per column: how much is empty, how
  many different values, the lowest and highest value, and what it looks
  like (emails, IDs…).
- **All my data** — the data itself: the first rows of each table, more
  rows when it asks (up to 200 at a time), the values of every category
  column, and error messages as they are. The most useful for analysing
  your data, and the one to think about before choosing it for an online
  server.

Only **All my data** sends rows. Changing the level is an edit to the
flow like any other — Ctrl+Z puts it back. Lowering it starts a fresh
chat, because every request repeats the conversation so far.

**Columns…** — one choice per column:

- **Hidden** — Flo never learns the column exists. It is left out of
  everything sent, and its name goes as `<column>` wherever it turns up.
- **Name only** — the default.
- **Name and values** — also its different values (the 100 most common),
  so Flo can filter on a category — a test name, a region — by its exact
  spelling instead of guessing.

The level is enforced by what Flo is *able* to ask for, not by asking it
nicely: at Nothing it is not given the tool that reads columns at all.

Whatever the settings, a **Hidden** column stays hidden (rows included),
passwords never go, and a file path goes as its file name only. Below All
my data, quoted values in an error message go as `'<value>'`.

## Where it goes

The card at the top says where your words go: **Local — nothing leaves
this PC** in green, or **Online — sent to *host*** in amber. Click the
connection name to switch; switching starts a fresh chat, so nothing the
last server was shown goes to the new one.

The first time you send to an online server, Flo asks first and lists
exactly what it will and will never see. Tick *Don't ask again for this
connection* to stop it asking; it asks again if the flow later lets it see
more.

**Can** — **Advise** lets it look and explain but not change anything;
**Act** lets it add, wire, set, rename and delete nodes, and run them.

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

## How it works on your flow

- It is given the whole node library with every request, so it knows what
  exists without guessing search words.
- A node it adds is placed beside, and wired to, the node that feeds it in
  one step. If it still leaves a required input empty, flograph tells it
  before it may answer, once per reply.
- Under **Act** it can run nodes on this PC to check its work or to learn
  the columns of something that has not run. What it is told about the
  result follows **Flo can see** — never rows. Running a node does what the node
  does: a writer writes its file.
- It is told not to delete, replace or rewire your nodes unless you ask for
  exactly that; asked to "improve" a flow, it suggests first.
- To keep it from losing its place on a long build, every change it makes
  is listed back to it; a repeated look-up or run with nothing changed is
  called out, and a node identical to one it already added is refused.
- Column settings are checked against what comes into the node: a name
  that isn't there, or a text column given to a chart's Y, comes back as a
  warning it can act on.
- When "this" or "it" is unclear it should ask — or point at the node with
  **Ask Flo** so there is nothing to guess.

Smaller free models often struggle with multi-step building. If replies
are muddled, try a stronger model on the same connection.

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
names, no rows.* — or, at All my data, how many rows went. **details**
lists the column names, which had their values or ranges sent, and whether
typed setting text was included. The receipt is read back from the requests that actually went,
not worked out from the dials, so it reports what left rather than what
should have.

At **Column names and summaries**, the lowest and highest value of number
and date columns are real values from your data; the receipt names those
columns. Set a column to **Hidden** to keep it out altogether.

## What was sent

Under every reply, **What was sent** shows the requests behind it, in full:
the instructions, your message as the AI got it (with any hidden names),
and every tool result. From the **⋯** menu:

- **Confirm Every Send** shows each request before it goes, with **Send**
  and **Don't Send**.
- **Open Send Log Folder** — every request is also written to a log on
  this PC, one file per day (`ai_log` in flograph's user folder), readable
  by you only.

## Not yet

It cannot write new node code yet — that comes later, behind the same
setting. Chats are not saved in the
flow: a flow you send someone never carries your conversation.
