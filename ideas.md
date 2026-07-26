1. LARGE: Markdown report creator, allowing me to write markdown but use things like ![[my chart]] to place the chart on the page, this will be exporting to things like pdfs. this could be anther page type like "model" "dashboard" so when you click the + icon in the bottom canvas bar, you have the option to pick dashboard or mdreport. or approperatly named options. ii like what you can do with R-markdown stuff, and would like to make a python version.
   PASS 1 DONE (report page kind, ![[node]] and ![[node|port]] embeds for
   figures/tables/scalars/markdown-strings, live preview, PDF export).
   Still to do, roughly in order:
   - page setup: size/orientation/margins, and a cover page
   - headers/footers with page numbers, title, date
   - page breaks you can force, and keeping a chart off a page boundary
   - plotly without needing kaleido (snapshot the webview instead)
   - figure sizing/alignment per embed, e.g. ![[chart|width=50%]]
   - export the whole project's reports at once / from the CLI (headless)
   - docx export?
   - a Report Text node so prose can be templated from data more easily
   - report *cards* exist now (Viz > Report, embeds its wired inputs,
     tileable on a dashboard); consider letting a page embed a card

   BIG ONE, agreed 2026-07-26, do as its own pass: HTML export via Jinja,
   then print from the browser. A SECOND export target alongside the PDF
   one, not a replacement.
   Why it's worth it — things Qt's text layout simply cannot do:
     - real CSS: @page, @media print, forced page breaks, page-break-inside
       avoid (the pagination weak spot), running headers/footers with
       counters
     - web fonts, flexbox/grid, proper design control
     - Plotly stays INTERACTIVE in the browser, and needs no kaleido —
       kills that limitation outright
     - browser print-to-PDF beats Qt for anything designed
   Shape:
     - a Jinja template the user can replace, plus a code node that injects
       CSS (fits how the rest of flograph works)
     - "Export HTML" + "Open in browser" buttons on a report page
     - the embed resolver already produces the right intermediate (values
       keyed by ref); only the *rendering* forks
     - asset handling: charts as embedded data URIs so one file travels
   Cost to be honest about: the in-app preview stops being exactly what you
   get. Today the preview and the PDF are literally the same QTextDocument
   so they cannot disagree; with a browser round trip the preview becomes an
   approximation and "open in browser" becomes the real preview.
   Groundwork already done 2026-07-26 by idea 21 (now shipped): the HTML
   coercion lives in flograph/core/html.py (Qt-free), and flograph/ui/
   browser.py writes a named page to a session temp dir and hands it to the
   desktop. A report's HTML export only has to produce the document — the
   "get it into a browser" half exists and is tested.
3. restore crashed workflows from undo history? how possible is this? 
7. right click nodes - deactivate.
20. node context option "Lock Node" this locks the node and retains its value on run all, does this work with cache? and on reopen, will it retain the value?
21. Report node - export to pdf on nodes context menu and show in browser? 
22. system mem and file mem: node mem: are these all the ram thats being used for this? can we have cache size, total app ram usage. maybe we can have a colored bar added that represents the system ram, the amount of ram this app is using, and the amount of ram the currrent selected node is using out of that. so one bar, colors layered over, and tooltip on hover? 
23. 