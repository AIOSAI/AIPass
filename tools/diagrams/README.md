# Diagram kit

Architecture pictures for AIPass READMEs, in one house style: navy background, glowing rounded tiles with white line icons, curved glowing connectors, faint circuit traces. Each picture is a JSON spec; one command renders it to SVG and PNG.

## Commands

```bash
python tools/diagrams/build.py how_it_works   # render one spec
python tools/diagrams/build.py --all          # render every spec
python tools/diagrams/build.py --check        # render every spec, verify each PNG matches its canvas
```

Output lands at the repo root: `assets/diagrams/<name>.png` and `assets/diagrams/src/<name>.svg`. The PNG comes from headless Chrome, Chromium or Edge; Inkscape is used only when none of those is on PATH. With neither, the build stops with an error.

## A spec

`tools/diagrams/specs/<name>.json`, explicit coordinates on the canvas (grid of 20), x and y are the top-left corner:

```json
{
  "title": "HOW IT WORKS",
  "subtitle": "one line under the title",
  "canvas": [1600, 900],
  "nodes": [
    {"id": "you", "kind": "tile", "icon": "person", "label": "you", "x": 60, "y": 400},
    {"id": "manager", "kind": "hub", "icon": "agent", "label": "MANAGER AGENT",
     "caption": "line one,\nline two", "x": 400, "y": 380, "w": 350, "h": 128},
    {"id": "gates", "kind": "tile", "icon": "shield", "label": "hooks", "x": 1500, "y": 400, "accent": "green"}
  ],
  "edges": [
    {"from": "you", "to": "manager", "label": "plain words"},
    {"from": "manager", "to": "gates", "from_side": "top", "to_side": "left"},
    {"from": "gates", "to": "manager", "style": "dashed", "accent": "green", "route": "bottom",
     "label": "reply", "labels": [{"text": "a second note", "at": "end"}]}
  ],
  "footers": ["first footer line", "second footer line"],
  "decor": {"traces": true, "pulse": true, "grid": true}
}
```

- **Nodes.** A `tile` is 88x88 with its label under it. A `hub` is wide (`w`, `h`) with label and caption inside. `accent` is `blue` (default) or `green`. A `\n` in a label or caption breaks the line.
- **Edges.** Edges join the facing sides of two nodes, and the axis with the larger gap wins. `from_side` and `to_side` override that choice. `route` of `bottom` or `top` carries a path around the outside of everything. `style` is `solid` or `dashed`, and `faint: true` dims an edge.
- **Labels.** `label_at` is `under` (default), `start` or `end`. Every label sits beside a straight run on a backing rect. `labels` adds more notes to the same edge.

The build refuses a spec that names an unknown icon, node id, kind or key, or whose tiles overlap. It also refuses text that collides with text or a node, a line that runs through a tile or a label, a hub too narrow for its text, and anything off the canvas. The refusal names the parts involved.

## Icons

`person` `chat` `folder` `agent` `gear` `document` `envelope` `inbox` `sparkle` `database` `shield` `list` `terminal` `phone` `dashboard` `clock` `brain`. Each is a function in `icons.py` that returns line-art markup for an 88x88 box.

`build.py` is the command. `theme.py` holds the colours, gradients, filters, geometry and fonts. `icons.py` holds the icon set. `render.py` turns SVG into PNG. `specs/` holds one JSON file per picture.

## Using a picture in a README

Reference the PNG by its absolute raw URL on `main`, so it renders on GitHub and on PyPI alike:

```markdown
![How it works](https://raw.githubusercontent.com/AIOSAI/AIPass/main/assets/diagrams/how_it_works.png)
```
