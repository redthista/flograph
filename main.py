"""Thin launcher for the flograph visual programming environment.

Dispatches through `flograph.cli`, so `python main.py run flow.flograph`
runs a flow headless just as `flograph run flow.flograph` does.
"""
from flograph.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
