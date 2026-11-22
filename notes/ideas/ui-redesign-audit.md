# UI redesign — Phase 0 audit

Card #116, part of #109. Spec: `docs/design/ui-ux-redesign-2026/flograph_ui_ux_redesign_goal_for_claude.md`.
Written 2026-11-22, against master `25a7d8d` and the theme worktree
(`.claude/worktrees/light-mode-pass`, branch `worktree-light-mode-pass`).
No code was changed for this audit.

## 1. Where theming stands today

There are three generations of theme work, and only the first is on master.

| Where | What it is | State |
| --- | --- | --- |
| **master** `ui/theme.py` (383 lines) | Light / Dark / **Follow system** (`THEME_PREFS`) for the *panels only*. The canvas, the title bar and the toolbar stay dark in Light. | Shipped |
| **`shelved/light-theme`** (87f1c0f, card #115) | Whole-window Light: per-mode canvas/wire/status tables, `theme.set_qss` so stylesheets re-skin, `MainWindow._on_app_theme_changed`, node shadow. 76 files. | Shelved |
| **`worktree-light-mode-pass`** | Base commit `50e818a` = an *earlier copy of the #115 rework* + a copy of the #108 Table work, 9 commits behind master. On top of it, **uncommitted**: themes as TOML data (`ui/themes/`: `dark.toml` reference with 163 keys in 10 sections, `light.toml`, `light_steel.toml`, user themes in `<user dir>/themes/`, `based_on` inheritance), a contrast checker (`themes/check.py`), a theme editor and preview, a Themes handbook page, about 6 test files. | Waiting for a user test since 2026-11-18 |

**Decision (2026-11-22):** Phase 1 builds on the TOML work. Because that
work sits on the #115 plumbing, building on it **brings #115's plumbing back
too**: `set_qss`, live re-skin, canvas-follows-theme. Only the per-mode
Python colour tables are replaced by the TOML files. The #115 card itself
stays Shelved and untouched.

### How a colour reaches the screen (worktree)

- **Widgets:** `theme.apply_theme(app, pref)` builds a `QPalette` (every role
  in all 3 groups) and an app stylesheet from the `ui` section. About 150
  per-widget stylesheets go through `theme.set_qss(widget, qss)`, which runs
  `skin()`: every *dark* hex the code was written with is mapped to a
  `(section, key)` role (`_SKIN_ROLES`), so old stylesheets re-colour without
  being rewritten. Under dark this is the identity.
- **Canvas items:** read module constants / `theme.color(section, key)` at
  paint time; `theme.on_change(cb)` (10 listeners) repaints cached items.
- **Follow system:** `styleHints().colorSchemeChanged` is connected in
  `mainwindow.py`.
- **Only one `from ..theme import CONSTANT`** is left (`report/busy.py`
  `BUTTON_ACCENT`), which a live switch would leave stale.

### Hard-coded colour inventory

| | master | worktree |
| --- | --- | --- |
| `#rrggbb` literals in `ui/**.py` | 872 in 76 files | 821 |
| raw `setStyleSheet(` calls | 156 | 12 (rest via `set_qss`) |
| `QColor("#…")` in canvas/dashboard paint code | — | 11 |

Most literals are **legitimate and must not be themed**:
`report/css_themes.py` (198) and `report/html.py` (58) are report/export
styles the author chose; `spreadsheet/icons.py` and `ribbon.py` are drawn
icon colours. Ones still to route through tokens:
`dashboard/tile_item.py` (update/stale pens `#60a5fa`/`#eab308`, white text),
`canvas/node_item.py` (`PROPOSED_COLOURS`, white glyph pens),
`canvas/minimap.py` (white tint base), `dashboard/format_pane.py` (swatch
checkerboard: fine as is), `report/busy.py`.

## 2. Architecture map (real paths)

| Area | Files / classes | Notes |
| --- | --- | --- |
| Window, docks, splitter persistence | `ui/mainwindow.py` (7210 lines), `dock_host.py`, `dock_edges.py` | Dock state in QSettings. |
| Title bar / toolbar | `ui/window_frame.py`, `toolbar.py`, `win_frame.py` | Drawn glyphs; see the `flograph-chrome` skill. **Stays dark in Light in both master and the worktree.** |
| Theme | `ui/theme.py`; worktree `ui/themes/`, `theme_editor.py`, `theme_preview.py`, `editor/theme_text.py` | |
| Canvas | `canvas/scene.py` `NodeGraphScene`, `view.py` / `base_view.py`, `grid.py` | |
| Processing nodes and cards | `canvas/node_item.py` (4950 lines): one item draws both the 60×60 node and every card kind | Size and LOD logic all here. |
| Wires | `canvas/connection_item.py`, `link_line.py`, `frame_port.py` | Order edges: `order_path`. |
| Frames | `canvas/frame_item.py` | User colour via `theme.tint` / `page_tint`. |
| Minimap | `canvas/minimap.py` | |
| Node Library | `canvas/palette.py` `LibraryTree` / `LibraryPanel`; `favorites.py` | |
| Search palette (Tab / dropped wire) | `canvas/node_search.py`, `core/wire_fit.py` | |
| Properties | `properties/params_panel.py` (2166 lines, QTreeWidget grid), `colour_row.py`, `var_completion.py`, `text_popout.py` | |
| Inspector (data preview) | `inspector/inspector_dock.py`, `pandas_model.py`, `figure_view.py`, `plotly_view.py`, `view_for.py` | |
| Log | `console/log_dock.py` (80 lines) | |
| Spreadsheet | `spreadsheet/view.py`, `model.py`, `ribbon.py`, `actions.py`, `menus.py` | Commands live once in `actions.py`. |
| WebEngine / Plotly | `webprofile.py`, `browser.py`, `inspector/plotly_view.py`, `report/plotly_snapshot.py` | |
| Dashboards / reports | `dashboard/dashboard_scene.py`, `tile_item.py`, `format_pane.py`; `report/*` | |
| Settings | `settings_dialog.py` (Appearance > Theme) | |
| Flo | `ui/flo/` | |

## 3. What the screenshots show

Offscreen window grabs, 1600×1000, flows `04_join_groupby_compare` (small
join flow) and `07_retail_ops_command_center` (large, multi-frame), not run.
Files are in `notes/ideas/ui-redesign-audit/`:
`before-master__*` (master) and `toml-worktree__*` (worktree), each `__dark` / `__light`.

1. **Light on master is half a theme:** light panels around a dark canvas and title bar.
   The worktree fixes the canvas. The title bar is still dark (decide in Phase 1).
2. **The idle Inspector dock is about a third of the window and empty**
   ("Nothing selected"), in every shot. That is the biggest layout win
   available, and belongs to Phase 6 (#122).
3. **Zoomed out (the large flow at about 27%), cards become blank blocks:**
   dark grey on master, flat white in the worktree's Light. Titles are
   unreadable and nodes can't be told from cards. This is the Phase 2 (#118)
   level-of-detail work.
4. **Wires:** cyan on master, as the spec says, and competing with frames.
   The worktree's light wires are quieter.
5. **The Properties panel is empty and wide** when nothing is selected (Phase 4, #120).
6. **Status bar:** memory/run readouts are already there (`resource_monitor.py`),
   which is relevant to #124.

What a grab can't show: WebEngine cards (blank offscreen), hover/focus
states, popups. Those are the user's manual pass.

## 4. Risks

1. **The worktree is behind master and duplicates #108.** Bringing it up to
   date means rebasing `50e818a` + the uncommitted TOML work onto master and
   dropping its copy of the Table helper-dropdown work. Expected conflicts:
   `mainwindow.py`, `spreadsheet/dropdown.py`, `canvas/scene.py`,
   `base_view.py`, plus whatever master changed in the 9 commits. Doing this
   **after #108 is committed** avoids rebasing twice.
2. **Plotly follows the theme only at display time.** Charts are built in a
   node's `run()` with `template` defaulting to `"default"` (white). Making
   them dark in Dark *inside the node* would make the theme re-run nodes and
   change saved output — forbidden. Theme-following must be applied by the
   card/report renderer (`inspector/plotly_view.py`, `report/*`) and only when
   the figure has no explicit template / `paper_bgcolor` / `plot_bgcolor` /
   chart rule. Exported reports keep the author's look.
3. **Cosmetic must not dirty.** Theme state must never be stored in node
   params. Per-node appearance already uses `"cosmetic": True` params; keep
   it that way.
4. **Live-switch staleness:** anything that copies a colour at construction
   time (the `report/busy.py` import, cached pixmaps, icons drawn once)
   shows the old theme until rebuilt. Each one needs an `on_change` hook;
   the screenshot test catches them.
5. **WebEngine pages** (Plotly, webview cards, wiki, Flo) need their
   background set before load to avoid a white flash in Dark.
6. **Size of `node_item.py` and `mainwindow.py`.** Changes there must stay
   surgical; no restructuring for the look.
7. **Join params (Phase 4):** adding `section` keys to `transform/join.py`
   PARAMS counts as a node change (bump `version` to 1.1). Separately, its
   `validate` default `""` isn't in its `options` list, a small existing
   quirk worth fixing then.

## 5. Phase 1 plan (#117), in order

Each step is one commit, tested by you before it's committed.

1. **Bring the theme work onto master.** After #108 is committed: rebase the
   worktree onto master, drop its duplicate Table changes, resolve conflicts,
   and run the full suite. Dark must stay pixel-identical to master (the
   worktree already has a tour + diff for this). *You test:* switch
   Light/Dark/System live, open a few flows.
2. **Map the spec's tokens onto the TOML keys.** Add a short table to
   `Themes.md` that relates each spec token (`app.bg`, `canvas.bg`,
   `panel.bg`, `node.bg`, `border`, `text.primary/secondary`,
   `accent.primary`, `connection.default/selected`) to its TOML key(s), and
   add any missing keys (selected wire, focus ring). Retune `light.toml` and
   `dark.toml` towards the spec's palette, keeping only values that pass
   `themes/check.py` contrast (WCAG AA for text, 3:1 for UI edges).
3. **Close the remaining hard-coded paint colours** listed in §1 (tile
   pens, proposed-node colours, minimap tint, `report/busy.py`), each one
   read from the theme at paint time.
4. **Title bar and toolbar in Light**, through the `chrome` section:
   decide whether they follow Light or stay dark. Ask before changing.
5. **Focus and disabled states:** a visible keyboard focus ring and readable
   disabled/secondary text in both themes (app stylesheet + palette roles).
6. **Plotly/web display-time defaults** (risk 2): theme-following
   background and template for figures with no explicit styling, cards and
   Inspector only, never exports.
7. **Regression net:** a test that switches theme N times and asserts no
   node is dirtied or run, no graph change is recorded, and no
   `QColor("#…")` is left in paint code outside the theme; plus the
   screenshot tour as a script under `scripts/`.

**Phase 1 exit:** Light / Dark / System coherent across the window, canvas,
editor, tables and cards; theme switches change no project data; Dark
matches master except where a change was intended.

## 6. Test flows

- **Small:** `templates/04_join_groupby_compare.flograph` covers the
  join-and-cards shape, so it is used instead of building the spec's
  Orders Q1/Q2 flow. A dedicated demo in `notes/flows/` only if a later phase
  needs the exact Q1+Q2 / Customers / Products merges.
- **Large:** `templates/07_retail_ops_command_center.flograph` (frames,
  dashboards), plus `scripts/bench_busy.py` for the performance side.
