# Changelog

## 0.1.8 (unreleased)

| Category | Change | Details |
| --- | --- | --- |
| Example | Folium Map | New bundled example (File > Open Example) demonstrating a web-view node that returns a raw `folium.Map` object directly — showing off the 0.1.7 fix that lets the webview card unwrap folium/branca objects without calling `get_root().render()` by hand. |

## 0.1.7

| Category | Change | Details |
| --- | --- | --- |
| Bug Fix | AI Assistant Settings crash fix | Fixed a `NameError` when opening the AI Assistant Settings dialog. |
| Bug Fix | Folium/branca maps in web-view nodes | Rendered via their standalone document instead of the Jupyter-only `_repr_html_()` iframe, which left a stuck "Make this Notebook Trusted to load map" placeholder over the map. |
| Bug Fix | Web-view nodes couldn't load CDN scripts | The embedded webview loads content from a local file, and Qt WebEngine blocks local content from fetching remote resources by default — so a folium/Leaflet map (or anything else pulling JS from a CDN) loaded but never ran. `LocalContentCanAccessRemoteUrls` is now enabled on the view. |
| Bug Fix | Scroll wheel over a web-view card zoomed the canvas | Hovering a folium/Leaflet map (or any other web-view card) and scrolling now lets the embedded map handle its own zoom/pan, instead of the wheel tick always zooming the graph canvas. |
| Bug Fix | One-file build script filename | `scripts/build_onefile_0_1_6.py` renamed to the unversioned `scripts/build_onefile.py` that the README, the script's own docstring, and `tests/test_onefile.py` all already expected — the test was silently failing. |
| Bug Fix | Node Library dock minimum width | Fixes the panel loading too thin, including for layouts saved before this fix existed. |
| Bug Fix | Settings dialog resize | Fixed Canvas page text being clipped top/bottom. |
| Feature | Configurable page bar position | Model/page tab strip can be pinned to the top or bottom of the window (Settings > General), persisted across sessions. |
| Feature | Dashboard Visuals panel toggle | Collapse/expand the Visuals panel on dashboard pages to give the canvas full width when it's not needed. |
| Feature | Disable SSL verification for AI requests | New "Verify SSL certificates" checkbox in AI Assistant Settings, for local/proxied LLM servers with self-signed certs. |
| Feature | Drag-and-drop file readers | Dropping a `.csv`/`.xlsx`/`.xls`/`.xlsm`/`.parquet` file from the OS file explorer onto the canvas creates the matching reader node with its path pre-filled. |
| Feature | Join node overhaul | The default Join node now supports the full range of pandas `join` features. |
| Feature | Password param type | Node scripts can declare `{"type": "password"}` in `PARAMS` for a masked field with a Show/Hide toggle. |
| Performance | GPU-accelerated canvas + zoom LOD | New **Tools > Settings…** (Ctrl+,) dialog; opt-in OpenGL viewport (auto-reverts if GL isn't available) and zoom-out node simplification to keep large graphs responsive. |
| UI | Code editor header cleanup | "Ask AI…", "Save as user node…", and "Reset to library" moved from the header down to the footer, next to Apply; the node title now stretches to fill the available width and elides with a tooltip instead of truncating at a fixed size. |
| UI | Properties panel redesigned as a resizable table | Node parameters now show in a two-column Property/Value table instead of an auto-generated form — drag the column divider to resize, so long labels or params never force the panel wider. |
| UI | Settings window reorganized | Snap-to-Grid and grid resolution moved from the toolbar into **Settings > Canvas**; page bar position got its own new **Settings > General** page. |
| UI | Snap-to-Grid on by default | Previously off by default; now enabled out of the box (toggle and grid resolution still configurable in Settings). |

## 0.1.6

Initial tagged baseline for this changelog — see git history prior to `v0.1.6` for earlier changes.
