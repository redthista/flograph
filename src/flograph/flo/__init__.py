"""The Flo Assistant: an AI that reads and builds the flow with you.

`tools` is what the model may do — read the flow, find node types, add and
wire nodes — every change an undoable command. `agent` runs one turn of the
conversation: model, tools, model, until it answers. What it may *see* is
decided in `flograph.core.ai_disclosure`; which server it talks to and how,
in `flograph.llm`.
"""
