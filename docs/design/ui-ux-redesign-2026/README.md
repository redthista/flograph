# flograph UI/UX redesign — reference assets

This directory contains the [Claude implementation specification](flograph_ui_ux_redesign_goal_for_claude.md) for issue [#109](https://github.com/redthista/flograph/issues/109).

## Visual mockup set

The following **six existing PNG concept images** are intended for `docs/design/ui-ux-redesign-2026/mockups/`:

| File | Design focus |
| --- | --- |
| `flograph_light_and_dark_mode_comparison.png` | Full Model workspace, matching light and dark modes |
| `flograph_processing_nodes_light_and_dark_modes.png` | Compact processing nodes (60×60), connection states and groups |
| `flograph_show_table_modes.png` | Canvas table card and expanded spreadsheet editor |
| `flograph_join_merge_panel_showcase.png` | Join/Merge Properties, grouping and field editors |
| `flograph_node_library_light_and_dark_modes.png` | Node Library and Tab search palette |
| `flograph_execution_console_mockup_sheet.png` | Execution dock, logs, previews, resource/status feedback |

**Upload status:** The textual specification is committed. PNG binaries remain to be uploaded before direct image links can be added to issue #109.

The archived mockups can be extracted directly under the repository root; their relative paths are already structured as `docs/design/ui-ux-redesign-2026/mockups/<filename>`.

### Design constraints

- Keep flograph's real model intact: processing steps are 60×60 nodes, while data/visualization elements are resizable live cards.
- Preserve existing keyboard shortcuts, property editing and search, caching, execution semantics, project formats, custom styles, report/dashboard rendering and node packs.
- Treat the images as visual concepts, **not** as authority for changing the documented behaviour.
