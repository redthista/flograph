"""What an order edge is, reachable by right-clicking one.

An order edge is the one thing on the canvas whose *absence* of behaviour is
the point — it carries nothing, so there is no output to inspect and no
value to hover, and a user who meets one on somebody else's flow has very
little to go on. This is that explanation, kept next to the feature rather
than in a manual nobody has open.

Non-modal, like the report reference it is modelled on: it is read while
rearranging a flow, so it must not block the canvas behind it.
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout


def reveal_key_name(key: int) -> str:
    """The reveal key as the user would say it — it is rebindable, so this
    dialog must not hardcode Q."""
    try:
        text = QKeySequence(key).toString()
    except Exception:      # pragma: no cover - defensive; any odd int
        text = ""
    return text or "the reveal key"


def order_edges_html(reveal_key: str = "Q") -> str:
    return f"""
<h3>An order edge</h3>
<p>This dashed line carries <b>no data</b>. It says one thing:
<b>run that node first</b>.</p>
<p>Every node has a small <b>flow pin</b> off each of its upper corners —
in on the left, out on the right. Drag from one node's right pin to another
node's left pin and you have ordered them.</p>

<h3>What it is for</h3>
<p>The steps whose order matters for a reason the flow itself cannot see,
because nothing is handed between them:</p>
<ul>
<li>write a file, <i>then</i> read it back</li>
<li>empty a table, <i>then</i> insert into it</li>
<li>fetch and cache something slow, <i>then</i> run the queries that expect
it to be there</li>
<li>finish a long job before a step that would otherwise compete with it for
the machine</li>
</ul>
<p>Without one, two such nodes have nothing joining them, so the engine is
free to start them together — and usually does.</p>

<h3>What it actually does</h3>
<ul>
<li><b>Orders the run.</b> The dependent node does not start until its
prerequisite has finished.</li>
<li><b>Pulls the prerequisite in.</b> Running the dependent on its own runs
whatever it waits on first.</li>
<li><b>Re-runs the dependent</b> when the prerequisite changes, and throws
away its cached result — which is the part that makes "write the file, then
read it" stay correct after you edit the writer.</li>
<li><b>Holds it back</b> if the prerequisite fails, or is deactivated.</li>
<li><b>Refuses a loop</b>, the same as any wire.</li>
</ul>
<p>A node can wait on <b>several</b> at once: wiring a second prerequisite
adds it rather than replacing the first.</p>

<h3>What it is not</h3>
<p>It passes <b>no value</b> — to move data, draw an ordinary wire. It is
also not a condition: it does not decide <i>whether</i> a node runs, only
<i>when</i>.</p>

<h3>Seeing the pins</h3>
<p>They are hidden until something is wired to them, since most flows never
need one. To bring them up:</p>
<ul>
<li><b>hold {reveal_key}</b> over the canvas — the same key that floats the
port names, for as long as you hold it;</li>
<li><b>Settings &#9656; Canvas &#9656; Show flow pins</b>, to keep them in
view;</li>
<li>a node's <b>Appearance…</b> dialog, to show or hide them on that node
alone.</li>
</ul>
<p>They also appear on their own while you drag an order edge, so there is
something to aim at.</p>

<h3>Removing one</h3>
<p>Click the dashed line and press <b>Delete</b>.</p>
"""


class OrderEdgeHelpDialog(QDialog):
    """Non-modal so it can stay open while the flow behind it is rearranged."""

    def __init__(self, parent=None, reveal_key: str = "Q") -> None:
        super().__init__(parent)
        self.setWindowTitle("Order edges")
        self.setModal(False)
        self.resize(560, 620)
        layout = QVBoxLayout(self)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        layout.addWidget(self._browser)
        self.set_reveal_key(reveal_key)

    def set_reveal_key(self, reveal_key: str) -> None:
        """Rewrite the text for the key that is bound right now — the dialog
        is reused across openings, and the binding can change between them."""
        self._browser.setHtml(order_edges_html(reveal_key))
