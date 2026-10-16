# Flo Assistant

The Flo Assistant is a chat beside the canvas that can read your flow and
change it. Ask for *"a bar chart of sales by region from my Excel reader"*
and it finds the right nodes, adds them, wires them up and sets their
options, and then tells you what it did.

Privacy comes first: the panel always shows where your words go, every
reply ends with a receipt of what left, and nothing is sent until you
press Enter.

Flo is an optional extra and starts **turned off**: tick **Settings ▸
General ▸ Flo Assistant ▸ Show the Flo Assistant** to turn it on. Until
you do, there is no Flo button, menu entry, shortcut or *Ask Flo* menu,
and Flo sends nothing; turning it off again closes the panel.

Once it is on, open it with **Tools ▸ Flo Assistant**, **Ctrl+Shift+A**,
or the **Flo** button on the title bar. It needs a connection first: see **Tools ▸ AI
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
**Propose** lets it make changes you look at before they count (see
*Proposals* below); **Act** lets it add, wire, set, rename and delete
nodes, run them, and make dashboard and report pages.

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
  result follows **Flo can see** — rows only at *All my data*. Running a
  node does what the node does: a writer writes its file.
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

## Pages

Flo can put what the flow makes in front of people, as pages:

- **Dashboards** — "make a dashboard of these charts" adds a page with a
  tile for each, laid out in rows. Only nodes that show something can be
  tiles: charts, tables, KPIs, slicers, controls, buttons, notes. Asked to
  tile a plain node, Flo is told to add a Show Table or a chart first. It
  can add more tiles to a page (below what is there) and take tiles off.
- **Reports** — a report page is markdown, and Flo writes it: headings,
  text, and `![[Label]]` embeds of your charts and tables. It names nodes
  by their handle and flograph swaps in the label, so an embed always
  points at a real node; an embed it can't resolve, or a label two nodes
  share, comes back to it as a warning. It can rewrite a report or add to
  its end. Ask for *interactive* or *live* charts and it adds `|live`, so
  the Web preview and the saved web page show the real chart (hover,
  zoom) rather than a picture; an option it gets wrong — `|interactive`,
  say — comes back to it with the list of the real ones.
- **Report styles** — it can give a report one of the starter themes
  (Midnight, Ledger, Swiss…) or one of your **saved snippets**, by name,
  the same list as the CSS tab's, with a few lines of its own on top if
  you ask. It replaces the page's CSS; if that was CSS you wrote by hand,
  it is told so, and Ctrl+Z brings it back. The look shows in the Web
  preview and the saved web page. For a look of its own — "make it look
  like frosted glass" — it reads the page's CSS and writes new CSS, which
  Ctrl+Z takes back like any change.
- **Web layout** — it can give a report a sidebar or a top bar, show one
  `#` section at a time (each section reads as a page of its own when
  picked), and add Previous / Next links. Asked to put something "on its
  own page" inside a report, it should ask whether you mean that or a
  separate page.
- **Links between pages** — it writes them as `[words](page:…)` by page,
  so they keep working if a page is renamed; a link to a page that does
  not exist comes back to it as a warning.
- It can also rename and delete pages — deleting only when you ask.
- **Report nodes** — ask for "a report node that describes this model"
  and Flo writes it on the canvas instead: a **Report** card, with the
  charts and tables it talks about wired into its inputs. It embeds them
  by the input they arrive on (`![[a]]`), as the card expects; a node it
  names but did not wire is embedded by its label, and Flo is told that
  such an embed shows the node but won't wait for it or re-run with it.

Page titles and report text are words you typed, so they follow **Flo can
see** like node labels and typed settings: at *Nothing from my data* it is
told how long a report is, not what it says. Canvas tabs are not pages to
Flo.

**Flo knows which page you are on.** Send a message while a dashboard or
report page is showing and it goes with a note naming that page — your
message shows *Looking at: <page>* — so "make this report darker" changes
the report's look, not the charts on the canvas behind it. On the canvas
nothing is added. Like every other change, a new page is part of the reply's undo step.

## Code

When no library node does what you asked — or you ask for code — Flo can
write a node's Python code: a node of its own (it adds a **Python
Script** node and writes that), or a change to one you already have.

**Flo applies its code itself**, as part of the reply's undo step: the
reply lists *Applied new code to …* with a **Review code** link that
opens the code editor on that node, and **Undo these changes** (or
**Ctrl+Z**) puts the old code back. Flo can then run the node to check its
work.

To read the code before anything runs it, untick **Can ▸ Apply Code It
Writes**. Flo's code then waits in the node's **code editor**, as Ask AI's
suggestions do, under *Flo wrote this code — it is not applied yet*; the
node keeps its old code until you press **Apply**, and nothing Flo wrote
runs until then — not even when Flo runs that node. **Undo these changes**
takes the waiting code back, unless you have edited it since. This is the
safer setting when Flo can see your data: text in a cell reaches the AI
too, and code it writes runs on this PC.

Code that waits for you is checked against the node rules without
running any of it; a node whose settings are built by code rather than
written out is checked fully when you press Apply.

What Flo reads: the library's code at any setting. **Code you wrote or
changed yourself** counts as your own text — at **Nothing from my data**
it is not sent; above that it is, with hidden column names replaced, and
the receipt lists it (*Code you wrote or changed, of 1 node*).

## Changes and undo

Each reply is **one undo step**, however many nodes it touched. The changes
are listed under the reply, each with a **show** link that takes you to the
node, and **Undo these changes** takes the whole reply back (or use
**Ctrl+Z**). Anything you change on the canvas while a reply is still
running joins that reply's undo step.

### Proposals

Under **Can ▸ Propose**, Flo makes the same changes it would under Act,
but as a proposal for you to look at first:

- **Nodes it adds** are faded inside a dashed purple outline, and so are
  the wires to them. They **don't run** — nor does anything they feed —
  until you keep them, and Flo can't run them either.
- **Nodes it changes** — a setting, a name, a new wire in — keep running
  as normal, inside a dashed amber outline.
- Under the reply: ***Proposed**: adds 2 nodes, 1 wire, changes 1
  setting — **Keep** · **Discard***.

**Keep** takes the outlines off, and the nodes are the flow's like any
other. **Discard** takes the whole proposal back. Ask for more before
deciding — "use a line chart instead" — and the next reply adds to the
same proposal, so one Discard still takes all of it back.

Discard works while the proposal is the last thing you did. Change
something yourself after it, or switch to **Act** and ask for more, and
the proposal counts as kept; **Ctrl+Z** back past it counts as
discarded. Code Flo writes in a proposal always waits in the code editor
for you to Apply, whatever **Apply Code It Writes** says. Nodes it
deletes go at once — the proposal lists them, and Discard brings them
back. The outlines aren't saved: a file saved while a proposal is
showing holds the flow as it stands, proposed nodes included, as
ordinary nodes.

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

### Tokens and cost

The receipt ends with how many **tokens** the reply took, as the server
counted them — *18.4k tokens in, 1.2k out*. Every request repeats the
conversation so far, so a long build's input count grows with each step;
**details** gives the exact numbers, and the running total for the whole
chat. **What was sent** shows the count of each request.

Some local servers and gateways don't report a count. The receipt then
says so rather than guessing, and *At least* means only some requests
reported one.

To see what a reply cost, type the server's prices into the connection in
**Tools ▸ AI Assistant Settings ▸ Price** — per million tokens, input and
output, from the provider's price page — and the receipt adds *≈ $0.07*.
It is worked out at those prices before any discount (cached prompts are
often cheaper), so it is a guide, not your bill. Leave Price blank and it
counts tokens only; changing it doesn't start a fresh chat.

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

Chats are not saved in the flow: a flow you send someone never carries
your conversation.
