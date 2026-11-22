"""Draft Emails

Open a new email in your default email app for each row of a table, filled
in and ready for you to read and send. Nothing is sent by flograph: every
draft waits for you. On Windows that is usually Outlook; elsewhere whatever
the system opens `mailto:` links with.

The table needs a **to** column. **cc**, **bcc**, **subject** and **body**
columns are used when present (any capitalisation). Several addresses in one
cell are separated by commas or semicolons. A row with no address is skipped.
Build per-row subjects and bodies upstream, with Merge Columns or a Python
node, from whatever the row says.

**Most emails** stops a table that is bigger than you meant from opening a
window per row; **Preview only** builds the links without opening anything.
Like every node, it runs again only when its table changes, so re-running an
unchanged flow does not open the drafts a second time. For a send-when-I-say
step, right-click it ▸ Run only when asked, and run it from an Action Button.

`mailto:` cannot carry attachments, and some email apps cut a very long body
short (Outlook at around 2,000 characters); the log says when a draft is
that long.

Outputs: `drafts` — one row per email (to, cc, bcc, subject, link, opened) —
and `count`, the number opened.
"""
NODE = {
    "label": "Draft Emails",
    "category": "Automation",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("drafts", "dataframe"), ("count", "number")],
}
OPEN = "Open the drafts"
PREVIEW = "Preview only"
PARAMS = [
    {"name": "mode", "type": "choice", "label": "When it runs",
     "options": [OPEN, PREVIEW], "default": OPEN},
    {"name": "max_emails", "type": "int", "label": "Most emails",
     "default": 20, "min": 1, "max": 500},
    {"name": "pause_s", "type": "float", "label": "Pause between (s)",
     "default": 0.5, "min": 0.0, "max": 10.0},
]

FIELDS = ("to", "cc", "bcc", "subject", "body")
#: past this a mailto: link is at risk of being cut short (ShellExecute and
#: Outlook both start trimming around here)
LONG_LINK = 2000


def _addresses(value):
    """'a@x.com; b@y.com' -> 'a@x.com,b@y.com' (mailto wants commas)."""
    import re

    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("", "nan", "none", "<na>"):
        return ""
    return ",".join(p.strip() for p in re.split(r"[;,]", text) if p.strip())


def _text(value):
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() in ("nan", "none", "<na>") else text


def mailto(to, cc="", bcc="", subject="", body=""):
    """The mailto: link for one draft. The address list stays readable;
    everything in the query is percent-encoded, line breaks as CRLF, which
    is what RFC 6068 asks for and what Outlook needs to keep them."""
    from urllib.parse import quote

    query = []
    for key, value in (("cc", cc), ("bcc", bcc)):
        if value:
            query.append(f"{key}={quote(value, safe='@,')}")
    if subject:
        query.append("subject=" + quote(subject, safe=""))
    if body:
        body = body.replace("\r\n", "\n").replace("\n", "\r\n")
        query.append("body=" + quote(body, safe=""))
    link = "mailto:" + quote(to, safe="@,")
    return link + ("?" + "&".join(query) if query else "")


def _open(link):
    """Hand one link to the system's mailto handler. Kept apart so a test can
    swap it out."""
    import os
    import subprocess
    import sys

    if sys.platform == "win32":
        os.startfile(link)  # noqa: S606 - the user's own default mail app
    elif sys.platform == "darwin":
        subprocess.run(["open", link], check=True, timeout=30)
    else:
        subprocess.run(["xdg-open", link], check=True, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(ctx, table):
    import time

    import pandas as pd

    p = ctx.params
    by_name = {str(c).strip().lower(): c for c in table.columns}
    if "to" not in by_name:
        raise ValueError(
            "the table needs a 'to' column (and optionally cc, bcc, subject, "
            f"body); it has: {', '.join(map(str, table.columns)) or 'no columns'}")
    columns = {f: by_name[f] for f in FIELDS if f in by_name}

    rows, skipped = [], 0
    for _, record in table.iterrows():
        values = {f: record[c] for f, c in columns.items()}
        to = _addresses(values.get("to"))
        if not to:
            skipped += 1
            continue
        draft = {
            "to": to,
            "cc": _addresses(values.get("cc")),
            "bcc": _addresses(values.get("bcc")),
            "subject": _text(values.get("subject")),
            "body": _text(values.get("body")),
        }
        draft["link"] = mailto(**draft)
        rows.append(draft)

    limit = int(p.get("max_emails") or 20)
    if len(rows) > limit:
        raise ValueError(
            f"{len(rows)} emails is more than 'Most emails' ({limit}); raise it "
            f"if you meant that many, or filter the table first")
    if skipped:
        ctx.log(f"skipped {skipped} row(s) with no address in 'to'")
    long = sum(1 for r in rows if len(r["link"]) > LONG_LINK)
    if long:
        ctx.log(f"{long} draft(s) are over {LONG_LINK} characters as a link; "
                f"some email apps cut the body short")

    preview = p.get("mode") == PREVIEW
    pause = float(p.get("pause_s") or 0.0)
    opened = 0
    for i, row in enumerate(rows):
        ctx.check_cancelled()
        row["opened"] = False
        if not preview:
            if i and pause:
                time.sleep(pause)   # one window at a time, in order
            _open(row["link"])
            row["opened"] = True
            opened += 1
        ctx.progress((i + 1) / len(rows))

    ctx.log(f"{'previewed' if preview else 'opened'} {len(rows)} draft(s)")
    drafts = pd.DataFrame(
        [{k: r[k] for k in ("to", "cc", "bcc", "subject", "link", "opened")}
         for r in rows],
        columns=["to", "cc", "bcc", "subject", "link", "opened"])
    return {"drafts": drafts, "count": opened}
