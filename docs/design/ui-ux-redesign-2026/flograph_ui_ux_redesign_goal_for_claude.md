# flograph — UI/UX Redesign Goal for Claude

**Project:** flograph — a desktop, node-based Python dataflow environment built with PySide6  
**Brief type:** Implementation goal, design specification and phased engineering plan  
**Primary objective:** A coherent, polished, efficient light/dark interface **without breaking the application users already have**.  
**Reference material:** The existing application screenshots, the before/after concept images, this repository, and the supplied flograph handbook (`Home.md`, `The-Canvas.md`, `Nodes-and-the-Library.md`, `The-Table-Spreadsheet.md`, `Dashboards-and-Reports.md`, `Writing-a-Node.md`, and related pages).

---

## 1. The goal — read this first

> **Redesign flograph's PySide6 desktop UI to feel like a mature, modern, professional visual development environment: the clarity of a good IDE, the discoverability of a visual programming tool, and the presentation quality of a data-analytics workspace. Make dark mode excellent and light mode equally first-class. Retain existing behaviour, dataflow semantics, power-user workflows, and the richness of the application's embedded cards and dashboards.**

This is **not** a request to rebuild flograph as a web application, replace the graphics engine, or replace functioning features with attractive but limited mockups. Treat the supplied redesign images as **visual direction**, not an exact widget tree or an authoritative specification of existing capabilities. The screenshots and help guide describe real functionality; the repository is the source of truth for implementation details.

The desired result is an application that:

- Looks calm, deliberate and consistently designed, even on complex graphs.
- Gives the **canvas most of the workspace** by default without hiding essential tools.
- Distinguishes **pipeline steps** from **data/view cards** instead of forcing everything into one node shape.
- Makes selection, data types, dirty/cached state, execution and errors instantly understandable.
- Uses light and dark colour systems that reach every native Qt and embedded web component.
- Preserves discoverability for new users and speed for expert keyboard users.
- Performs well on large projects, high-DPI displays, and flows with many live tables, charts and wires.
- Can be implemented incrementally and validated after every phase.

### Non-negotiables

1. **Do not rewrite the engine, node contracts, project format, cache model or execution semantics to accomplish a visual redesign.** Only touch these if required for a separately approved feature, with a compatibility plan.
2. **Preserve all existing keyboard shortcuts and configurable canvas interaction modes.** Do not change F5/F6, Tab search, F to fit, Ctrl+G frames, Q for port labels, the configured mouse gestures, or context menu operations.
3. **Preserve the compact 60×60 processing-node design described in `The-Canvas.md`.** Apply a cleaner visual treatment; do not turn every processing step into a large data card. Nodes that hold previews or controls remain live, resizable cards.
4. **Preserve existing properties functionality:** typed `PARAMS`, conditional visibility, searchable properties, the `Changed` filter, reset to default, variable bindings, section folding, keyboard focus and safe scrolling over controls.
5. **Preserve user-assigned colours and custom formats.** Theme defaults must not overwrite explicit node, frame, page, tile, table or chart styling.
6. **Preserve real output functionality:** spreadsheet editing, dashboard tiles, interactive Plotly/webviews, images/PDFs, reports, run/caching states, managed folders and Flo Assistant privacy controls.
7. **UI-only changes must not mark nodes dirty or trigger recomputation.** Changing a theme, resizing a panel, viewing a result or changing a purely cosmetic setting must not rerun the flow.
8. Keep accessibility, keyboard focus and contrast measurable; do not rely on hue alone to convey status.
9. Prefer contained, reversible, tested changes. **Do not undertake a broad architecture rewrite just to modernise the look.**

---

## 2. What exists today — important functional context

This brief is based on the supplied screenshots and handbook. Do not overlook how much functionality already exists.

### Existing visual workspace

- A `Model` canvas and separate `Overview`, `Detail`, `Executive` dashboard/report tabs.
- A searchable **Node Library** with favourites and categories.
- An infinite Blueprint-style canvas with frames, node ports, wires, reroutes, minimap, customisable gestures and zoom.
- **Compact processing steps** as 60×60 nodes, and larger live-card nodes for tables, charts, KPIs, controls, reports and previews.
- A right **Properties** dock: selected node descriptions, searchable typed settings, grouped sections, changed-only filtering, reset-to-default and conditional inputs.
- A code editor, logs and an Inspector.
- Run All, Run Selected, cache reset, status and a resource monitor.
- On-canvas spreadsheet cards with a mini-ribbon, tabs and spreadsheet behaviour; inline chart/Plotly/KPI/report cards.
- Frames which can group nodes, run conditionally, collapse, open in new tabs or become nested model canvases; cross-canvas connections via Goto/From and variables.
- A `.flograph` project with output caches and a `.flowf` workflow-only export; graphical and headless runs.
- Optional Flo Assistant with explicit privacy levels and local/online model visibility.

### Specific observations from the screenshots

- Current dark mode uses several very similar, dark surfaces, so the canvas, cards and panels tend to merge visually.
- The bright cyan wiring attracts more attention than the underlying processing structure.
- Large node graphs become visually noisy at overview zoom, with tiny labels and many crossing wires.
- The right inspector becomes difficult to scan when properties have truncated labels and narrow value editors (e.g. a Merge/Join node with key columns, join type, suffixes and cardinality validation).
- The bottom log dock consumes substantial screen height when idle.
- The node library has high information density but could use more consistent iconography, selected states and spacing.
- Embedded previews need stronger framing, good empty states and theme consistency.
- The application already has effective technical workflows; the redesign should refine presentation and interaction rather than replace them.

---

## 3. Before → after targets

| Surface | Before / current experience | After / required experience |
|---|---|---|
| Overall appearance | Dark, flat and densely delineated | Layered but restrained; consistent typography, spacing, accents and separators |
| Light mode | Needs an equally coherent design pass | A polished soft-grey workspace, white surfaces, dark readable text and accessible accents |
| Canvas | Wires, frames, cards and background compete | Canvas stays visually primary; understated grid; active elements stand out |
| Processing nodes | Technically effective compact squares | Keep **60×60** and floating labels; refine marks, ports, selection and status at every zoom |
| Live cards | Rich but heterogeneous mini-apps | Consistent host chrome, padding and status treatment while preserving custom card internals |
| Wires | Bright cyan across much of the graph | Quiet by default, clear on hover/selection; preserve types, flow pins and directional meaning |
| Frames | Useful but visually heavy | Translucent, clearly titled frames with stronger hierarchy and unobtrusive boundaries |
| Node Library | Long compact hierarchical list | Better scanning, search, favourites, category icons, keyboard selection and drag affordances |
| Properties | Narrow labels and editors | Resizeable, grouped, legible form; useful help; same typed controls and Changed workflow |
| Console | Large blank area when unused | Resizeable, collapsible dock; clear status summary; rich log and Inspector still available |
| Execution | Mostly small status lights and logs | Visible states in nodes, on canvas and in status; detailed per-node diagnostics when selected |
| Tables and charts | Inconsistent contrast between surfaces | Theme-aware native tables, Chart/Plotly/webviews, well-designed loading/empty/error states |
| Dashboards/reports | Powerful but inconsistent visual defaults | Consistent defaults while preserving author-controlled formatting and print/export integrity |
| Minimap | Colour blocks not always easily interpreted | Simplified readable graph view; strong viewport box; no excessive repainting |

---

## 4. Visual design system

Build a small **semantic token system** rather than scattered hard-coded QSS colours. Keep colour definitions, typography, dimensions and states centrally defined and usable by QWidgets, QGraphicsItems and web content.

### Suggested colour tokens (starting point, subject to contrast testing)

| Semantic token | Dark | Light |
|---|---|---|
| `app.bg` | `#141922` | `#F4F6FA` |
| `app.toolbar` | `#1B2230` | `#FFFFFF` |
| `panel.bg` | `#202A39` | `#FFFFFF` |
| `panel.raised` | `#293649` | `#FFFFFF` |
| `canvas.bg` | `#111821` | `#EEF2F7` |
| `canvas.grid` | `#2B3749` | `#D8E1EB` |
| `node.bg` | `#273344` | `#FFFFFF` |
| `node.header` | `#303F53` | `#E9EEF5` |
| `border.subtle` | `#364559` | `#D8E0EA` |
| `text.primary` | `#E6EDF7` | `#1D2939` |
| `text.secondary` | `#A7B7CB` | `#5B6B7D` |
| `text.muted` | `#8293A9` | `#718096` |
| `accent.primary` | `#7AA9FF` | `#2869E8` |
| `focus.ring` | `#92B9FF` | `#205DD6` |
| `status.success` | `#45C99B` | `#16845B` |
| `status.warning` | `#F3BD64` | `#A46108` |
| `status.error` | `#F47D84` | `#BD3448` |
| `status.running` | `#7AA9FF` | `#2869E8` |
| `connection.default` | `#60899A` | `#7395A4` |
| `connection.selected` | `#72DADE` | `#168E9A` |

Treat these as design tokens, **not a requirement to replace a user's chosen colours**. Test all text/control states against the actual backgrounds; dark-mode palettes must not reduce secondary text to unreadable grey. Where contrast fails, adjust the token rather than accepting a decorative colour.

### Typography and spacing

- Use a clean Qt-available UI sans-serif and platform fallback; do **not** bundle unlicensed fonts.
- Normal UI labels: ~12–13 px equivalent at 100% UI scale; section headings ~13–14 px semibold; code uses a readable monospace font.
- Typical spacing scale: **4 / 8 / 12 / 16 / 24 px**. Panels have consistent padding; dense data tables remain dense by choice.
- Small radii (~5–8 px) for normal components. Avoid enormous radii on every rectangle.
- Prefer 1 px borders and subtle surface contrast over thick separators and heavy shadows.
- Use consistent SVG/vector icons sized roughly 14–18 px for toolbar/list controls; Qt icon sizes should follow high-DPI scaling.
- Provide keyboard-visible focus rings, logical tab order, meaningful disabled state and accessible tooltips.

### Theme propagation

Changing theme via the **existing Settings ▸ General ▸ Appearance ▸ Theme** must update **Dark / Light / Follow system**, live, without restarting or recomputing the graph. Audit all the places that need explicit updates:

- `QPalette` + scoped Qt style sheets for native controls and docks.
- `QGraphicsScene`/`QGraphicsView` background, nodes, frames, paths, ports, labels, minimap, popups and selection rectangle.
- Native table and spreadsheet viewports, row/column headers, selection, sort/filter dropdowns and cell editor.
- Code editor backgrounds, syntax highlighting, line numbers, breakpoints/errors, active-line and search highlights.
- Property editor widgets, form controls, hover/focus and disabled states.
- `QWebEngineView` content and Plotly visualisation defaults; carefully distinguish **follow-theme defaults** from explicit plot/page styles.
- Report/web preview, dashboard tiles, rich-text cards and their loading/error placeholders.
- Dialogs, dock chrome, scrollbars, floating palettes, menus, tooltips, status bar and embedded images/PDF viewers where applicable.

Avoid dynamically rewriting exported HTML/PDF or report author CSS simply because the editor theme changed. Keep report content and application chrome separate.

---

## 5. Workspace layout and navigation

### Maintain the familiar overall shape

- **Top:** application/title controls and clear, grouped Run All (`F5`), Run Selected (`F6`), cache reset and optional Flo access; below this, the page/tab strip.
- **Left:** searchable Node Library with favourites and category grouping.
- **Centre:** flexible, dominant canvas with a compact floating toolbar and a minimap.
- **Right:** contextual Properties / Code / relevant Inspector experience, in a resizable panel.
- **Bottom:** a resizable, collapsible Logs / Inspector area, with optional richer Execution/Problems views only where already supported or deliberately added.
- **Footer:** one-line run status, active node, zoom, memory and transient messages.

### Layout requirements

- Do not impose fixed sidebar widths; use splitters and dock restore/persistence.
- Offer a **Canvas Focus** or equivalent layout that collapses supplementary panels without losing their state; respect existing **Hide all panels** command.
- Add useful empty states rather than blank large surfaces. When no node is selected, the properties pane can show a short hint or collapse — never obscure the canvas.
- Keep controls reachable at a typical laptop resolution and at 125–200% OS scaling.
- Retain all existing tabs and drag/rename/group/fold semantics. A Model canvas tab is not the same thing as a dashboard tab or a report page.
- Give context-sensitive panels a meaningful title and distinct selection feedback. Do not silently switch the user's tab when a background node completes.
- Separate **global run controls** from **node-specific actions** visibly; do not change their behaviour or shortcuts.

### Node Library improvements

- Clear search field, keyboard navigation and active match highlighting.
- Preserve favourites, categories, custom node packs, extension categories and drag-to-canvas behaviour.
- Consistent category icons and readable group headers; avoid making favourite/node icons artificially dominant.
- Show node description and type/package/version in tooltip or supporting detail as available, with compatibility hints where the existing palette provides them.
- Keep the `Tab`/right-click add-node palette, type-matched node suggestions and the wire-splice / node-replace workflows intact.

---

## 6. Canvas, nodes, wires and frames

### Canvas

- Draw a faint adaptive dot grid or similarly restrained background; implement efficiently in the view's background painting, **not as thousands of individual scene items**.
- Offer a compact tool row for select/pan, fit view and zoom, without covering important content.
- Preserve `F`, middle/Space pan, configurable left-drag behaviour, wheel/Ctrl-wheel options, Shift-wheel horizontal scrolling, Q port labels, multi-selection and optional infinite scrollbars.
- Minimap remains optional and lightweight; selected viewport clearly visible and draggable if it already supports that interaction.
- High-DPI, large graphs and min/max zoom need deliberate testing.

### Processing nodes (critical: don't turn them into cards)

- Keep existing **60×60 square processing nodes** and their compact, consistent graph rhythm.
- Make marks/icons, floating titles, ports, status lights, selection outlines and optional appearance customisation crisp in both themes.
- Preserve shape/colour/mark/port-label customisation, per-node themes and user-custom marks/images.
- Preserve semantic states: clean/success, dirty/out-of-date, running, failed, deactivated, frozen, run-on-request, bypassed, dropped output and any existing other state. Do not collapse all these into a generic green tick.
- Make statuses understandable by shape, icon and tooltip, not just colour.
- At zoomed-out levels, **reduce decorative detail first**, preserving the silhouette, status/selection and useful graph structure. Semantic zoom/LOD is recommended, but must not remove interactive ports or lead to impossible hit targets at normal working zoom.
- Ensure selected and hovered nodes are obvious without becoming oversized or repositioned.

### Live cards

- Keep card-specific dimensions and full functionality for table/spreadsheet cards, charts, KPIs, controls, PDF/image previews, reports and custom webviews.
- Introduce a consistent **outer card host**: title, status and standard buttons (expand, move/resize and existing widget actions). Keep each card's own internal toolbar and editor intact.
- Standardise empty/loading/stale/error/complete states. For example: Table Spec not yet run should explain why and offer the **existing** way to run the flow, without implying a new execution API.
- Preserve on-canvas chart interaction and spreadsheet input, data validation and ribbon editing; they are not screenshots.

### Wires and ports

- Start from calmer, slightly desaturated default connections with sufficient contrast.
- Brighten the hovered/selected wire, selected node's connected wires and compatible drag target; dim unrelated wires cautiously while a node is selected.
- Preserve typed port compatibility and suggestions, reroute dots and wire-splice/replace gestures.
- Preserve **order-only edges/flow pins** as visually distinct dashed connections, with current dependency behaviour unchanged.
- Keep hit target separate from the visible stroke so slender wires are still easy to select.
- Avoid high-frequency glows and continuous animations across large graphs. Running feedback should be lightweight and optional/reduced-motion friendly.
- When wires overlap frame regions and data cards, ensure layering is intentional and ports remain discoverable.

### Frames and nested canvases

- Use soft, translucent frame fills and crisp but quiet borders. Headers have clear title and meaningful group colour.
- Preserve drag-with-contents, collapse/reopen, gated execution, multi-selection, `Ctrl+G`, nested model canvas conversion, tab views of frames, and undo semantics.
- Preserve the users' frame colours: if a colour was chosen, use it thoughtfully rather than forcibly replacing it with the theme accent.

---

## 7. Properties — a priority redesign target

The screenshot of the **Merge/Join** node is a concrete acceptance example. It contains node name, key-column selectors, join type, suffixes, a merge indicator, and cardinality validation. The current panel is functional but hard to scan.

### Proposed experience

- Use a **~320–400 px preferred inspector width**, still user-resizable. Do not assume one fixed pixel size at every display scale.
- Keep a concise node summary (icon, name, one-line description and info access) at the top.
- Use labelled, collapsible semantic groups, such as **General**, **Join Keys**, **Join Options** and **Validation**, when the existing schema supports groups. Do not invent storage fields solely to fill a visual form.
- Prefer full labels on their own row over a tiny two-column grid where the label is regularly truncated. Where space allows, a responsive two-column design is acceptable.
- Make default vs changed settings obvious (existing bold-label semantics or a restrained dot/count).
- Keep `Search properties` and the `Changed` button visible. Preserve resetting a property/section via Undo.
- Retain typed `PARAMS`, dynamic options, `visible_when`, `unset_label`, column pickers, wizards, `node_ref`, `page_ref`, variable bindings, password handling and file pickers.
- Preserve safe wheel behaviour: scrolling the panel must not accidentally alter a closed combo/spin box.
- Provide accessible input feedback: focus border, validation message, concise hint/tooltips, disabled explanation and meaningful placeholder text.
- A selected Merge node should make it easy to understand *which columns join*, *which side each key belongs to*, *what join type is selected*, and *which validation mode applies*.
- Ensure edits bind to the **existing undo/dirty/caching semantics**; merely expanding a section or moving focus does not count as a property change.

**Important:** a polished generic property editor must not break node-specific property widgets, conditionally visible sections, the existing help behaviour or dynamic column choices.

---

## 8. Tables, analytics visuals and dashboard/report surfaces

### Tables and spreadsheet

- Use matching semantic surface/text/selection tokens in both themes: header cells, alternating rows if enabled, selected row/cell, focus, gridlines, edit indicator, filter menus and formula bar.
- Keep the existing mini-ribbon **Home / Insert / Rows & Columns / Data / Review / View / Formulas**, formula editing, validation, formatting, range selection, undo, freeze, groups and pivot/chart features.
- **Do not rerun the flow for cosmetic table changes.** The handbook explicitly distinguishes display changes from edits to values, names and types.
- Preserve held edits and **Submit (`F9`)** mode; show pending edits clearly without auto-applying them.
- Keep column names visible, data alignment correct and overflow/tooltips usable at common zoom levels.
- Use efficient view painting, not expensive per-cell widget instantiation for large datasets.

### Charts and embedded web views

- Update default Plotly backgrounds, axis/grid/legend/text/hover labels to match the app theme **only where the user has not explicitly set a style**.
- Handle embedded `QWebEngineView` content carefully: plot containers and surrounding host should not have white flashes or mismatched chrome in dark mode.
- Preserve all Plotly interactions, webview JS bridges and live card behaviour; do not rewrite generated data HTML simply to colour it.
- Respect `Chart Rules`, conditional formatting and explicit user colour choices. Maintain offline/locally installed web-library behaviour.
- Provide coherent blank/loading/renderer error placeholders without hiding real diagnostics.

### Dashboards and reports

- Give newly created dashboard pages and tiles attractive **theme-aware defaults**, but respect stored per-page and per-tile backgrounds, title colours, custom formatting, lock state and author intent.
- Preserve dashboard tile aspect ratios, zoom/fit, rearranging, fullscreen, locks and interactive controls.
- Preserve markdown/report authoring and PDF/HTML/export presentation. App shell dark/light must **not** silently change a saved report's designed print colours.
- Preserve Flo Assistant integration and its explicit visibility/privacy/connection-state indicators; do not send data or prompts just because its panel opened.

---

## 9. Execution, feedback and diagnostics

### Immediate visual changes (safe UI work)

- Make the current flow status intelligible: **Idle / Running / Finished / Out of date / Failed / Cancelled**, using the statuses actually exposed by the engine.
- Distinguish per-node state via compact badge/light and tooltip. Preserve cache/stale/freeze/bypass indicators.
- Display known timing, last run, error and resource metrics where already available; avoid invented values or made-up percentage completion.
- Give the logs consistent severity styling, clickable node references where the existing data supports it, search/copy/clear and sensible auto-scroll behaviour.
- Default the bottom dock to a compact height and remember the user's preferred expanded height.
- A failure should be actionable: identify node, message, traceback/code location if available, and provide a way to select/focus that node.

### Optional debugging enhancements (separate approval)

The screenshots and guide confirm logs, inspector output, code error markers and node-level execution behaviour. They **do not, by themselves, establish** a true Python breakpoint/step-through debugger. Do not pretend one exists.

If requested after the visual work, propose a distinct engineering phase for real breakpoints, variable watches, call stacks, stepping or pausing. This requires engine/thread/state design and reliable cancellation/recovery, not merely adding inert tabs or buttons. It must not compromise the existing concurrent dirty-subgraph runner.

A visual-only Execution panel may initially show reliable events already emitted by the engine. Hide unavailable controls rather than shipping decorative controls that do nothing.

---

## 10. PySide6 implementation approach

**First audit the actual codebase; identify classes rather than inventing them.** The architecture below is a recommendation to apply to what exists, not a claim that these classes or module names already exist.

### Recommended responsibilities

| Responsibility | Suggested approach |
|---|---|
| Theme definitions | Central semantic token map for dark/light/system |
| Theme switching | Single theme manager applying `QPalette`, scoped QSS and explicit repaints to custom-painted widgets |
| Main window | Existing `QMainWindow`/dock/splitter layout and saved geometry; avoid wholesale replacement |
| Canvas | Existing `QGraphicsView` / scene custom painting with theme lookup and selective invalidation |
| Processing nodes | Shared visual primitives for label/mark/ports/status, preserving the 60×60 item and hit geometry |
| Frame rendering | Themed brushes/pens, header visuals, preserved scene and nested-canvas semantics |
| Property editing | Shared style/delegate/layout layer around existing `PARAMS`-driven widgets and signals |
| Node library | Improve existing model/view tree/delegate/search, do not replace registry or node-pack discovery |
| Tables | Palette-aware item delegate/view/header with existing data models and editing rules |
| Charts/web views | Per-theme default templates and embedded HTML CSS variables where controllable, explicit style overrides retained |
| Code editor | Theme-specific syntax token colours and editor chrome, independent of Python execution |
| Execution | Subscribe to existing state/log signals; do not modify scheduling just for an indicator |
| Persistence | Existing UI preferences store for theme/layout/zoom; project content untouched unless required |

### Engineering constraints

- Avoid global unscoped QSS selectors that accidentally override custom widgets or embedded pages.
- Avoid per-frame rebuilding of entire scenes or recreating large Qt widget trees on hover.
- Avoid adding a `QGraphicsItem` for every background dot/grid line.
- Use Qt high-DPI-aware units, device pixel ratio handling and batched invalidation.
- Keep icon resources local and redistributable; avoid network fonts/assets or CDN dependencies.
- When a card uses `QWebEngineView`, test initial render, resize, theme switch, JS event channel, stale-state updates and process recovery.
- UI operations should not mutate the graph's computational state. Keep model, view and engine side effects separated.
- Ensure theme transitions do not leave cached brushes, pixmaps or rendered scenes in the wrong theme.
- Follow existing code style and public interfaces; favour small reusable components instead of a giant stylesheet.

---

## 11. Phased implementation plan

### Phase 0 — Repository and UX audit (**no code changes initially**)

1. Inspect the repository and trace how the main window, docks, graph items, properties, embedded cards, theme switching, Plotly/webview host and persistence work.
2. Map each screenshot section to the real source files/classes/functions. Identify any existing light-mode support and partial theme tokens.
3. Identify all hard-coded colours, fonts and visual dimensions without bulk-replacing them blindly.
4. Establish a reliable before baseline: screenshots at comparable zoom/scroll, smoke tests for the bundled example flows, and a record of normal shortcut behaviour.
5. Deliver a small architecture map and an ordered change list with **actual repository paths**. State assumptions/unknowns rather than guessing.

**Exit:** We know where to make targeted changes and have baseline evidence that the app works.

### Phase 1 — Unified theme foundation (**first implementation milestone**)

1. Add/extend semantic colour, typography, spacing, icon and state tokens.
2. Implement live Dark / Light / Follow system propagation across native Qt chrome and main canvas.
3. Restyle menus, toolbars, tabs, dock titles, splitters, scrollbars, tooltips, input controls, search and status bar.
4. Fix table and Plotly/webview theme defaults, without overwriting custom charts.
5. Add focused screenshot checks and tests for switching both ways while a project is loaded.

**Exit:** The **same flow** looks cohesive in both themes, with no execution difference or loss of custom colours.

### Phase 2 — Canvas, nodes and frames

1. Refine canvas background and grid.
2. Refine compact processing node rendering, statuses, focus/selection and port visibility; **retain 60×60 semantics**.
3. Refine connection strokes, hover, selection, type targeting and order-edge distinction.
4. Refine frame chrome, titles and minimap appearance.
5. Apply a consistent host treatment to live cards without altering their internals.
6. Performance-test graph overview (e.g. the existing screenshots' ~29% zoom) and detailed editing (~100–120%).

**Exit:** Large graphs are significantly easier to scan; all established node gestures and wiring actions still work.

### Phase 3 — Property panel and layout polish

1. Restyle the Node Library with better row hierarchy, icons, focus and search results.
2. Make Properties readable, labelled and sectioned while retaining dynamic `PARAMS`, Changed/search/reset/variable flows.
3. Improve default dock sizes and stored collapse/expand behaviour.
4. Add better empty states and keyboard focus; refine code editor chrome and visual contrast.
5. Test the Merge/Join properties example end-to-end.

**Exit:** A user can find a node, connect it, configure joins and inspect results quickly, even on laptop-sized screens.

### Phase 4 — Execution, outputs and dashboard/report polish

1. Harmonise status, error, stale and log rendering around existing signals.
2. Restyle full spreadsheet/ribbon/table selection and editing.
3. Refine live charts, dashboard tile states, embedded views and report authoring defaults.
4. Inspect high-DPI, theme switching, print/export, resource use and concurrency regressions.
5. Only then consider separate debugger/execution-insight functionality if approved.

**Exit:** The whole app — not just its shell — behaves and looks cohesive in both themes.

### Working approach for each phase

- Show the planned affected files/classes first.
- Implement in modest patches; do not mix unrelated refactors.
- For each patch: describe the UI effect, why it is safe, tests added, and what remains unverified.
- Run unit/smoke tests and review side-by-side screenshots before declaring the phase done.
- If a requirement conflicts with existing functionality, preserve functionality and propose an alternative.

---

## 12. Acceptance criteria / definition of done

### Appearance

- [ ] Dark theme has clear hierarchy between canvas, toolbar, nodes, panels and embedded content.
- [ ] Light theme is fully usable and stylistically equal, not a quick colour inversion.
- [ ] Switching Dark ↔ Light ↔ System updates all native and embedded UI without restart.
- [ ] Default typography, row heights, icons, spacing and focus states are consistent.
- [ ] Controls and text remain readable at normal and 125–200% display scaling.
- [ ] User-custom colours, chart styles and report formatting survive switching and reopening.

### Graph interaction

- [ ] The same loaded test flow still runs and yields identical results.
- [ ] Processing nodes remain the documented compact 60×60 size.
- [ ] Live cards still render/interact in the canvas and in dashboard tiles.
- [ ] Wire draw/reconnect/splice/replace, reroutes, typed ports and order edges still work.
- [ ] Frame moves, collapse, run modes, new tab and nested-model behaviour still work.
- [ ] Zoom/pan options, minimap, scrollbars and keyboard shortcuts still work.
- [ ] The canvas remains responsive with many nodes, frames, wires and embedded cards.

### Properties and navigation

- [ ] The Merge/Join inspector remains fully editable (keys, join type, suffixes, indicator, validation).
- [ ] Property search, Changed, sections, dynamic visibility and reset/Undo still work.
- [ ] `Tab` add-node palette, library search, favourites and node-pack categories still work.
- [ ] Collapsing/resizing side and bottom docks does not lose values or controls.
- [ ] Focus and scrolling a property panel do not accidentally change settings.

### Execution and outputs

- [ ] Run All `F5`, Run Selected `F6`, cancellation and caching have unchanged semantics.
- [ ] Per-node stale, clean, error, running, freeze/bypass/drop-output states remain distinguishable.
- [ ] No purely visual edit invalidates a node cache.
- [ ] The spreadsheet mini-ribbon, formulas, formatting and pending Submit mode work.
- [ ] Plotly interaction, webview bridges, dashboard controls, report previews and exports work.
- [ ] Flo Assistant remains opt-in with exactly its existing privacy and model routing protections.
- [ ] `.flograph`/`.flowf` files still load/save and existing projects are backwards compatible.

### Validation matrix

Test each stage on at least:

- A small linear source → transform → output flow.
- The screenshot-like **Orders Q1 / Orders Q2 → Join/Enrich → Table Spec** flow.
- A large multi-frame analytical flow at **overview and working zoom**.
- A dashboard with KPI cards, Show Table, Show Plotly and interactive controls.
- A spreadsheet with formulas/conditional formatting, including edits held until Submit.
- A flow with failed, dirty, frozen, bypassed and dropped-output nodes.
- A workflow using Flo Assistant (with both the panel disabled and enabled), without changing data-visibility permissions.
- Both dark/light themes, system theme switching, resized docks, and at least one high-DPI environment.

Record screenshot comparisons under identical viewport, zoom and content so improvements can be judged fairly. Include any genuine performance change, not only visual impressions.

---

## 13. Out of scope unless separately approved

- Replacing PySide6 with Electron, a browser frontend, a game engine or another toolkit.
- Replacing the dirty-subgraph executor, changing node Python APIs, changing cached output format or project schema.
- A true new step-through debugger, breakpoints/watch stack or pause/resume engine controls.
- Cloud sync, collaboration, new AI abilities, authentication, user telemetry or network calls.
- Deleting/replacing powerful but visually complex spreadsheet/report features to make a screenshot look simpler.
- Changing report export styles independently of the report author's formatting settings.
- Invisible, decorative buttons whose advertised functions are not implemented.

---

## 14. Exact starter instruction to send Claude

Copy/paste the following into your coding session together with this file and repository access:

> **Please treat `flograph_ui_ux_redesign_goal_for_claude.md` as the authoritative UI/UX goal.** Study the existing PySide6 repository and the flograph help-guide files before changing code. The screenshots show the real application; the concept images show desired visual direction. Preserve everything specified under Non-negotiables, especially the **60×60 processing nodes versus live visual cards**, the existing `PARAMS`-driven property editor, all shortcuts/gestures, the cache/execution model and `.flograph` compatibility.
>
> **Start with Phase 0 only.** Identify the real files/classes responsible for the main window, themes, canvas, processing-node and card rendering, wires, frames, minimap, Properties, Node Library, logs, Qt WebEngine/Plotly and dashboards. List existing theme support and hard-coded styling, identify technical risks, and propose an ordered Phase 1 implementation with acceptance checks and files to edit. Do **not** start a sweeping refactor. Once the audit is established, implement Phase 1 in small testable changes, comparing both light and dark screenshots against the original flows. Keep functionality and data compatibility ahead of visual fidelity whenever they conflict.

### Deliverables expected from Claude

1. Repository architecture map with **real** paths and key classes.
2. Theme/visual-component inventory and prioritised change list.
3. Small, reviewed patches corresponding to the phased plan.
4. Screenshots of the same flow in before/current, after/dark and after/light states.
5. Automated and manual regression results, with remaining gaps explicitly labelled.
6. Updated documentation for any settings or interactions that genuinely changed.

---

## 15. Design reference and interpretation notes

The design comparison images are **concept art**, not pixel-perfect UI measurements. They may contain stylised labels, simplified graphs and illustrative data. **Never infer a new feature or a specific API from them.** Use the actual screenshots, help-guide pages and running repository when in doubt.

The handbook is especially important for:

- `The-Canvas.md`: the 60×60 node rule, cards, frames, order edges, Q/Tab/F/F5/F6 gestures, minimap and theme settings.
- `Nodes-and-the-Library.md`: typed property widgets, search, Changed filter, favourites and node categories.
- `Writing-a-Node.md`: public node contracts, card kinds, dynamically generated params and webview bridges.
- `The-Table-Spreadsheet.md`: input behaviour, held edits/Submit, formula bar and non-computational formatting.
- `Dashboards-and-Reports.md`: live canvas cards, dashboards, tile formatting, interactive webviews and report/PDF expectations.
- `Input-Controls.md`, `Flow-Variables.md` and `Flo-Assistant.md`: current UI behaviour and strict data/privacy considerations.
- `Chart-Rules.md` and `Conditional-Formatting.md`: user-authored style rules that a theme must not destroy.

**Design north star:** *Powerful like an IDE. Visually legible like a well-organised analysis workspace. Calm and coherent in either theme. No loss of what makes flograph distinctive.*