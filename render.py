"""Render a daily worksheet JSON (sheets/YYYY-MM-DD.json) to a PDF in output/.

Usage: .venv/bin/python render.py sheets/2026-10-26.json

Math strings use a tiny LaTeX-like syntax:
  x^{-2}        superscript
  \\frac{a}{b}   stacked fraction
  \\cdot         multiplication dot
  \\times        multiplication cross (scientific notation)
  \\text{...}    upright words, spaces kept
Letters render italic (variables); digits and symbols render upright.
"""

import json
import sys
from pathlib import Path

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
pdfmetrics.registerFont(TTFont("Serif", str(FONT_DIR / "Times New Roman.ttf")))
pdfmetrics.registerFont(TTFont("Serif-Italic", str(FONT_DIR / "Times New Roman Italic.ttf")))
pdfmetrics.registerFont(TTFont("Serif-Bold", str(FONT_DIR / "Times New Roman Bold.ttf")))

GRAY = Color(0.45, 0.45, 0.45)
LIGHT = Color(0.93, 0.93, 0.93)
RULE = Color(0.75, 0.75, 0.75)

PAGE_W, PAGE_H = letter
MARGIN = 0.6 * 72
COL_GAP = 14
CELL_H = 108


# ---------- math layout boxes ----------

class Text:
    def __init__(self, s, size, italic=False):
        self.s, self.size = s, size
        self.font = "Serif-Italic" if italic else "Serif"
        self.w = pdfmetrics.stringWidth(s, self.font, size)
        self.asc, self.desc = 0.72 * size, 0.22 * size

    def draw(self, c, x, y):
        c.setFont(self.font, self.size)
        c.drawString(x, y, self.s)


class Space:
    def __init__(self, w):
        self.w, self.asc, self.desc = w, 0, 0

    def draw(self, c, x, y):
        pass


class Row:
    def __init__(self, items):
        self.items = items
        self.w = sum(i.w for i in items)
        self.asc = max((i.asc for i in items), default=0)
        self.desc = max((i.desc for i in items), default=0)

    def draw(self, c, x, y):
        for i in self.items:
            i.draw(c, x, y)
            x += i.w


class Raised:
    def __init__(self, box, rise):
        self.box, self.rise = box, rise
        self.w = box.w
        self.asc = box.asc + rise
        self.desc = max(0, box.desc - rise)

    def draw(self, c, x, y):
        self.box.draw(c, x, y + self.rise)


class Frac:
    def __init__(self, num, den, size):
        self.num, self.den = num, den
        self.axis = 0.27 * size
        self.gap = 0.18 * size
        self.pad = 0.15 * size
        self.w = max(num.w, den.w) + 2 * self.pad
        self.asc = self.axis + self.gap + num.desc + num.asc
        self.desc = max(0, self.gap + den.asc + den.desc - self.axis)

    def draw(self, c, x, y):
        line_y = y + self.axis
        c.setLineWidth(0.8)
        c.line(x, line_y, x + self.w, line_y)
        self.num.draw(c, x + (self.w - self.num.w) / 2, line_y + self.gap + self.num.desc)
        self.den.draw(c, x + (self.w - self.den.w) / 2, line_y - self.gap - self.den.asc)


def _read_group(s, i):
    """s[i] must be '{'. Return (inner_text, index_after_closing_brace)."""
    assert s[i] == "{", f"expected '{{' at {i} in {s!r}"
    depth, j = 0, i
    while True:
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1


def layout(s, size):
    items = []
    i = 0
    while i < len(s):
        ch = s[i]
        if s.startswith("\\frac", i):
            num, i = _read_group(s, i + 5)
            den, i = _read_group(s, i)
            items.append(Frac(layout(num, size), layout(den, size), size))
            continue
        if s.startswith("\\cdot", i):
            items += [Space(0.25 * size), Text("·", size), Space(0.25 * size)]
            i += 5
            continue
        if s.startswith("\\times", i):
            items += [Space(0.25 * size), Text("×", size), Space(0.25 * size)]
            i += 6
            continue
        if s.startswith("\\text", i):
            words, i = _read_group(s, i + 5)
            items.append(Text(words, size))
            continue
        if ch == "^":
            exp, i = _read_group(s, i + 1)
            items.append(Raised(layout(exp, 0.68 * size), 0.42 * size))
            continue
        if ch == " ":
            i += 1
            continue
        if ch in "=+<>≤≥":
            items += [Space(0.28 * size), Text(ch, size), Space(0.28 * size)]
        elif ch == "-":
            items.append(Text("−", size))
        elif ch.isalpha():
            items.append(Text(ch, size, italic=True))
        else:
            items.append(Text(ch, size))
        i += 1
    return Row(items)


# ---------- page drawing ----------

class Sheet:
    def __init__(self, data, out_path):
        self.data = data
        self.c = canvas.Canvas(str(out_path), pagesize=letter)
        self.c.setTitle(f"{data['title']} - {data['date']}")
        self.page = 1
        self.y = PAGE_H - MARGIN

    def footer(self):
        c = self.c
        c.setFont("Serif", 9)
        c.setFillColor(GRAY)
        c.drawString(MARGIN, MARGIN / 2, f"Sheet {self.data['date']}")
        c.drawRightString(PAGE_W - MARGIN, MARGIN / 2, f"Page {self.page}")
        c.setFillColor(black)

    def new_page(self):
        self.footer()
        self.c.showPage()
        self.page += 1
        self.y = PAGE_H - MARGIN

    def ensure(self, h):
        if self.y - h < MARGIN:
            self.new_page()

    def header(self):
        c = self.c
        c.setFont("Serif-Bold", 20)
        c.drawString(MARGIN, self.y - 20, self.data["title"])
        c.setFont("Serif", 11)
        c.drawRightString(PAGE_W - MARGIN, self.y - 18, self.data["date"])
        self.y -= 34

    def reminder(self):
        c = self.c
        rules = [layout(r, 13) for r in self.data["reminder"]]
        ex = self.data["example"]
        steps = [layout(s, 13) for s in ex["steps"]]

        rule_h = sum(r.asc + r.desc + 8 for r in rules)
        step_h = sum(s.asc + s.desc + 6 for s in steps) + 18
        box_h = max(rule_h, step_h) + 26
        x0, w = MARGIN, PAGE_W - 2 * MARGIN
        top = self.y

        c.setFillColor(LIGHT)
        c.setStrokeColor(RULE)
        c.roundRect(x0, top - box_h, w, box_h, 6, stroke=1, fill=1)
        c.setFillColor(black)

        c.setFont("Serif-Bold", 11)
        c.drawString(x0 + 12, top - 16, "Rules to remember")
        y = top - 24
        for r in rules:
            y -= r.asc
            r.draw(c, x0 + 16, y)
            y -= r.desc + 8

        ex_x = x0 + w * 0.42
        c.setStrokeColor(RULE)
        c.line(ex_x - 12, top - 10, ex_x - 12, top - box_h + 10)
        c.setFont("Serif-Bold", 11)
        c.drawString(ex_x, top - 16, ex["label"])
        y = top - 30
        for s in steps:
            y -= s.asc
            s.draw(c, ex_x + 8, y)
            y -= s.desc + 6

        self.y = top - box_h - 16

    def section(self, sec):
        cols = 2
        cell_w = (PAGE_W - 2 * MARGIN - COL_GAP * (cols - 1)) / cols
        qs = sec["questions"]
        rows = [qs[i:i + cols] for i in range(0, len(qs), cols)]

        # keep directions with the first row
        self.ensure(24 + CELL_H)
        self.directions(sec["directions"])
        for row in rows:
            self.ensure(CELL_H + 8)
            for k, q in enumerate(row):
                self.cell(q, MARGIN + k * (cell_w + COL_GAP), self.y, cell_w)
            self.y -= CELL_H + 8
        self.y -= 6

    def directions(self, text):
        c = self.c
        c.setFont("Serif-Bold", 12)
        c.drawString(MARGIN, self.y - 13, text)
        c.setStrokeColor(black)
        c.setLineWidth(0.6)
        c.line(MARGIN, self.y - 18, PAGE_W - MARGIN, self.y - 18)
        self.y -= 26

    def cell(self, q, x, top, w):
        c = self.c
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.roundRect(x, top - CELL_H, w, CELL_H, 4, stroke=1, fill=0)

        c.setFont("Serif-Bold", 12)
        c.setFillColor(black)
        c.drawString(x + 8, top - 18, f"{q['n']}.")

        expr = layout(q["expr"], 16)
        expr.draw(c, x + 30, top - 8 - expr.asc)

        ans_y = top - CELL_H + 12
        c.setFont("Serif", 10)
        c.setFillColor(GRAY)
        c.drawString(x + w - 150, ans_y, "Answer:")
        c.setStrokeColor(GRAY)
        c.line(x + w - 112, ans_y - 2, x + w - 10, ans_y - 2)
        c.setFillColor(black)

    def build(self):
        self.header()
        self.reminder()
        for sec in self.data["sections"]:
            self.section(sec)
        self.footer()
        self.c.save()


def main():
    src = Path(sys.argv[1])
    data = json.loads(src.read_text())
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{src.stem}.pdf"
    Sheet(data, out).build()
    print(out)


if __name__ == "__main__":
    main()
