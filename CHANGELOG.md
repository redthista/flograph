# Changelog

## 0.1.7 (unreleased)

| Category | Change | Details |
| --- | --- | --- |
| Bug Fix | AI Assistant Settings crash fix | Fixed a `NameError` when opening the AI Assistant Settings dialog. |
| Bug Fix | Node Library dock minimum width | Fixes the panel loading too thin, including for layouts saved before this fix existed. |
| Bug Fix | Settings dialog resize | Fixed Canvas page text being clipped top/bottom. |
| Feature | Configurable page bar position | Model/page tab strip can be pinned to the top or bottom of the window (Settings > General), persisted across sessions. |
| Feature | Dashboard Visuals panel toggle | Collapse/expand the Visuals panel on dashboard pages to give the canvas full width when it's not needed. |
| Feature | Disable SSL verification for AI requests | New "Verify SSL certificates" checkbox in AI Assistant Settings, for local/proxied LLM servers with self-signed certs. |
| Feature | Drag-and-drop file readers | Dropping a `.csv`/`.xlsx`/`.xls`/`.xlsm`/`.parquet` file from the OS file explorer onto the canvas creates the matching reader node with its path pre-filled. |
| Feature | Join node overhaul | The default Join node now supports the full range of pandas `join` features. |
| Feature | Password param type | Node scripts can declare `{"type": "password"}` in `PARAMS` for a masked field with a Show/Hide toggle. |
| Performance | GPU-accelerated canvas + zoom LOD | New **Tools > Settings…** (Ctrl+,) dialog; opt-in OpenGL viewport (auto-reverts if GL isn't available) and zoom-out node simplification to keep large graphs responsive. |
| UI | Settings window reorganized | Snap-to-Grid and grid resolution moved from the toolbar into **Settings > Canvas**; page bar position got its own new **Settings > General** page. |
| UI | Snap-to-Grid on by default | Previously off by default; now enabled out of the box (toggle and grid resolution still configurable in Settings). |

## 0.1.6

Initial tagged baseline for this changelog — see git history prior to `v0.1.6` for earlier changes.
