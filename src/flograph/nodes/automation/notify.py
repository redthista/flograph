"""Notify

Send a message when a flow reaches this node — a run finished, a quality gate
failed, a file landed. Wire it downstream of the thing worth announcing; use
an order edge (the `flow` port) when there's no data to pass.

**Channel**:

  • `slack` / `discord` — an incoming-webhook URL; the message posts as text
  • `webhook` — POST the message (and any wired `data`) as JSON to any URL
  • `ntfy` — a topic URL (`https://ntfy.sh/my-topic`) for phone push
  • `email` — SMTP; set host / port / user / password and a from/to address

Secrets belong in the project's `.env` — reference them as
`${env:SLACK_WEBHOOK}` / `${env:SMTP_PASSWORD}`. The `subject` and `message`
accept `${name}` flow variables. Needs `httpx` for the webhook channels.
"""
NODE = {
    "label": "Notify",
    "category": "Automation",
    "version": "1.0",
    "inputs": [
        ("message", "any", {"optional": True}),
        ("data", "any", {"optional": True}),
    ],
    "outputs": [("sent", "bool"), ("detail", "string")],
}
PARAMS = [
    {"name": "channel", "type": "choice", "label": "Channel",
     "options": ["slack", "discord", "webhook", "ntfy", "email"],
     "default": "slack"},
    {"name": "endpoint", "type": "string", "label": "Webhook / topic URL",
     "default": "", "placeholder": "${env:SLACK_WEBHOOK}",
     "visible_when": {"channel": ["slack", "discord", "webhook", "ntfy"]}},
    {"name": "subject", "type": "string", "label": "Subject",
     "default": "", "placeholder": "flograph: nightly load"},
    {"name": "message", "type": "text", "label": "Message",
     "default": "", "placeholder": "Run finished. ${rows} rows loaded."},
    {"name": "smtp_host", "type": "string", "label": "SMTP host",
     "default": "", "visible_when": {"channel": "email"}},
    {"name": "smtp_port", "type": "int", "label": "SMTP port",
     "default": 587, "min": 1, "max": 65535,
     "visible_when": {"channel": "email"}},
    {"name": "smtp_user", "type": "string", "label": "SMTP user",
     "default": "", "visible_when": {"channel": "email"}},
    {"name": "smtp_password", "type": "password", "label": "SMTP password",
     "default": "", "placeholder": "${env:SMTP_PASSWORD}",
     "visible_when": {"channel": "email"}},
    {"name": "email_from", "type": "string", "label": "From",
     "default": "", "visible_when": {"channel": "email"}},
    {"name": "email_to", "type": "string", "label": "To",
     "default": "", "placeholder": "comma separated",
     "visible_when": {"channel": "email"}},
    {"name": "on_error", "type": "choice", "label": "On send failure",
     "options": ["fail", "warn"], "default": "fail"},
]


def _body(message, data):
    text = message or ""
    if data is None:
        return text
    try:
        import pandas as pd
        if isinstance(data, pd.DataFrame):
            preview = data.head(20).to_string(index=False)
            return f"{text}\n\n```\n{preview}\n```" if text else preview
    except Exception:  # noqa: BLE001
        pass
    return f"{text}\n\n{data}" if text else str(data)


def run(ctx, message=None, data=None):
    p = ctx.params
    channel = p.get("channel", "slack")
    subject = (p.get("subject") or "").strip()
    text = message if isinstance(message, str) else (p.get("message") or "")
    text = _body(text, data)
    if not text.strip() and not subject:
        raise ValueError("nothing to send — set 'Message' (or wire one in)")

    try:
        if channel == "email":
            detail = _send_email(p, subject, text)
        else:
            detail = _send_webhook(channel, p, subject, text, data)
    except Exception as exc:  # noqa: BLE001
        if p.get("on_error", "fail") == "fail":
            raise
        ctx.log(f"notify failed ({exc}) — continuing")
        return {"sent": False, "detail": str(exc)}

    ctx.log(f"sent via {channel}: {detail}")
    return {"sent": True, "detail": detail}


def _send_webhook(channel, p, subject, text, data):
    import httpx

    url = (p.get("endpoint") or "").strip()
    if not url:
        raise ValueError("no webhook URL — set 'Webhook / topic URL'")
    full = f"*{subject}*\n{text}" if subject else text

    if channel == "slack":
        payload, kw = {"text": full}, {}
    elif channel == "discord":
        payload, kw = {"content": full[:1900]}, {}
    elif channel == "ntfy":
        payload = None
        kw = {"content": text.encode(),
              "headers": {"Title": subject} if subject else {}}
    else:  # generic webhook
        payload = {"subject": subject, "message": text}
        if data is not None:
            try:
                import pandas as pd
                if isinstance(data, pd.DataFrame):
                    payload["data"] = data.to_dict("records")
            except Exception:  # noqa: BLE001
                pass
        kw = {}

    with httpx.Client(timeout=20.0) as client:
        resp = (client.post(url, json=payload, **kw) if payload is not None
                else client.post(url, **kw))
    resp.raise_for_status()
    return f"{resp.status_code} {url.split('/')[2]}"


def _send_email(p, subject, text):
    import smtplib
    from email.message import EmailMessage

    host = (p.get("smtp_host") or "").strip()
    to = [a.strip() for a in (p.get("email_to") or "").split(",") if a.strip()]
    frm = (p.get("email_from") or p.get("smtp_user") or "").strip()
    if not host or not to or not frm:
        raise ValueError("email needs 'SMTP host', 'From' and 'To'")

    msg = EmailMessage()
    msg["Subject"] = subject or "(no subject)"
    msg["From"] = frm
    msg["To"] = ", ".join(to)
    msg.set_content(text or "")

    port = int(p.get("smtp_port", 587))
    user = (p.get("smtp_user") or "").strip()
    pw = p.get("smtp_password") or ""
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with cls(host, port, timeout=30) as s:
        if port != 465:
            s.starttls()
        if user:
            s.login(user, pw)
        s.send_message(msg)
    return f"emailed {len(to)} recipient(s)"
