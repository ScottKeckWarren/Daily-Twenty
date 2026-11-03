"""Render a daily worksheet JSON (sheets/YYYY-MM-DD.json) to a PDF in output/.

Usage: .venv/bin/python render.py sheets/2026-10-26.json [--key]

--key fills in color-by-number grids (writes output/<name>-key.pdf).
The finished PDF opens in Preview for printing.

Math strings use a tiny LaTeX-like syntax:
  x^{-2}        superscript
  \\frac{a}{b}   stacked fraction
  \\cdot         multiplication dot
  \\times        multiplication cross (scientific notation)
  \\text{...}    upright words, spaces kept
  \\sqrt{a}      square root; \\sqrt[3]{a} cube root
Letters render italic (variables); digits and symbols render upright.
"""

import json
import random
import subprocess
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
RULE_LINE_H = 24  # extra cell height for the "Rule:" line


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


class Sqrt:
    def __init__(self, inner, size, index=None):
        self.inner, self.size = inner, size
        self.index = layout(index, 0.62 * size) if index else None
        self.lead = self.index.w * 0.6 if self.index else 0
        self.rad_w = 0.5 * size
        self.w = self.lead + self.rad_w + inner.w + 0.12 * size
        self.asc = inner.asc + 0.16 * size
        self.desc = inner.desc + 0.04 * size

    def draw(self, c, x, y):
        s = self.size
        bot, top = y - self.desc, y + self.asc
        h = top - bot
        x0 = x + self.lead
        c.setLineWidth(0.07 * s)
        p = c.beginPath()
        p.moveTo(x0, bot + 0.45 * h)
        p.lineTo(x0 + 0.1 * s, bot + 0.52 * h)
        p.lineTo(x0 + 0.24 * s, bot)
        p.lineTo(x0 + 0.44 * s, top)
        p.lineTo(x + self.w, top)
        c.drawPath(p, stroke=1, fill=0)
        c.setLineWidth(0.8)
        if self.index:
            self.index.draw(c, x, bot + 0.6 * h)
        self.inner.draw(c, x0 + self.rad_w, y)


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
        if s.startswith("\\sqrt", i):
            i += 5
            index = None
            if s[i] == "[":
                j = s.index("]", i)
                index, i = s[i + 1:j], j + 1
            inner, i = _read_group(s, i)
            items.append(Sqrt(layout(inner, size), size, index))
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
        if ch in "=+<>≤≥≠÷":
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
    def __init__(self, data, out_path, key=False):
        self.data = data
        self.key = key
        self.rule_line = data.get("rule_line", False)
        self.cell_h = data.get("cell_height", CELL_H + (RULE_LINE_H if self.rule_line else 0))
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
        self.ensure(24 + self.cell_h)
        self.directions(sec["directions"])
        for row in rows:
            self.ensure(self.cell_h + 8)
            for k, q in enumerate(row):
                self.cell(q, MARGIN + k * (cell_w + COL_GAP), self.y, cell_w)
            self.y -= self.cell_h + 8
        self.y -= 6

    def intro(self, text):
        c = self.c
        c.setFont("Serif-Italic", 11)
        for line in text.split("\n"):
            c.drawString(MARGIN, self.y - 12, line)
            self.y -= 15
        self.y -= 10

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
        c.roundRect(x, top - self.cell_h, w, self.cell_h, 4, stroke=1, fill=0)

        c.setFont("Serif-Bold", 12)
        c.setFillColor(black)
        c.drawString(x + 8, top - 18, f"{q['n']}.")

        expr = layout(q["expr"], 16)
        expr.draw(c, x + 30, top - 8 - expr.asc)

        ans_y = top - self.cell_h + 12
        c.setFont("Serif", 10)
        c.setFillColor(GRAY)
        c.drawString(x + w - 150, ans_y, "Answer:")
        c.setStrokeColor(GRAY)
        c.line(x + w - 112, ans_y - 2, x + w - 10, ans_y - 2)
        if self.rule_line:
            # right under the question, so the work space stays in one block
            rule_y = top - 8 - expr.asc - expr.desc - 16
            c.drawString(x + 8, rule_y, "Rule:")
            c.line(x + 34, rule_y - 2, x + w - 10, rule_y - 2)
        c.setFillColor(black)

    def color_by_number(self):
        """Color key plus a grid of squares, each labeled with one answer.

        data["grid"] is a list of strings, one character (a color code) per
        square. Each square is labeled with the answer to one of that color's
        questions, picked at random (seeded) so the labels mix.
        """
        c = self.c
        colors = {col["code"]: col for col in self.data["colors"]}
        answers = {q["n"]: q["answer"] for sec in self.data["sections"] for q in sec["questions"]}
        grid = self.data["grid"]
        rng = random.Random(self.data.get("seed", 1))

        c.setFont("Serif-Bold", 16)
        c.drawString(MARGIN, self.y - 16, "Color by Number")
        self.y -= 30

        # key: 4 entries per row
        per_row = 4
        entry_w = (PAGE_W - 2 * MARGIN) / per_row
        for i, col in enumerate(self.data["colors"]):
            x = MARGIN + (i % per_row) * entry_w
            y = self.y - (i // per_row) * 36
            c.setFillColor(Color(*col["rgb"]))
            c.setStrokeColor(GRAY)
            c.rect(x, y - 16, 16, 16, stroke=1, fill=1)
            c.setFillColor(black)
            c.setFont("Serif-Bold", 11)
            c.drawString(x + 22, y - 9, col["name"])
            c.setFont("Serif", 10)
            nums = col["questions"]
            label = "Questions " + ", ".join(map(str, nums[:-1])) + f" & {nums[-1]}" if len(nums) > 1 else f"Question {nums[0]}"
            c.drawString(x + 22, y - 21, label)
        self.y -= 36 * ((len(colors) + per_row - 1) // per_row) + 6

        cols = len(grid[0])
        s = (PAGE_W - 2 * MARGIN) / cols
        # stretch rows to fill the page, up to 1.4x taller than wide
        sh = min(1.4 * s, (self.y - MARGIN) / len(grid))
        counts = {}
        for r, line in enumerate(grid):
            for k, code in enumerate(line):
                x, top = MARGIN + k * s, self.y - r * sh
                if self.key:
                    c.setFillColor(Color(*colors[code]["rgb"]))
                    c.rect(x, top - sh, s, sh, stroke=0, fill=1)
                c.setStrokeColor(RULE)
                c.setLineWidth(0.5)
                c.rect(x, top - sh, s, sh, stroke=1, fill=0)

                ans = answers[rng.choice(colors[code]["questions"])]
                counts[ans] = counts.get(ans, 0) + 1
                box = layout(ans, 10.5)
                if box.w > s - 3:
                    box = layout(ans, 8)
                c.setFillColor(black)
                box.draw(c, x + (s - box.w) / 2, top - sh / 2 - (box.asc - box.desc) / 2)
        self.y -= len(grid) * sh

        missing = [a for a in answers.values() if counts.get(a, 0) < 2]
        if missing:
            print("warning: answers shown fewer than 2 times:", missing, file=sys.stderr)

    def cheat_sheet(self):
        """Reference cards in two columns, each placed in the shorter column.

        data["cards"]: [{"heading", "rules": [...], "examples": [...], "tips": [...]}]
        """
        c = self.c
        cols = 2
        w = (PAGE_W - 2 * MARGIN - COL_GAP * (cols - 1)) / cols
        size = 12
        tops = [self.y] * cols

        for card in self.data["cards"]:
            rules = [layout(r, size) for r in card.get("rules", [])]
            exs = [layout(e, size) for e in card.get("examples", [])]
            tips = [layout(t, size) for t in card.get("tips", [])]
            for box in rules + exs + tips:
                if box.w > w - 24:
                    print(f"warning: line too wide in {card['heading']!r}", file=sys.stderr)

            h = 28 + sum(b.asc + b.desc + 7 for b in rules)
            if exs:
                h += 20 + sum(b.asc + b.desc + 7 for b in exs)
            if tips:
                h += 20 + sum(b.asc + b.desc + 7 for b in tips)
            h += 6

            k = max(range(cols), key=lambda i: tops[i])
            if tops[k] - h < MARGIN:
                self.new_page()
                tops = [self.y] * cols
                k = 0
            x, top = MARGIN + k * (w + COL_GAP), tops[k]

            c.setStrokeColor(RULE)
            c.setLineWidth(0.8)
            c.roundRect(x, top - h, w, h, 6, stroke=1, fill=0)
            c.setFillColor(LIGHT)
            c.roundRect(x, top - 22, w, 22, 6, stroke=0, fill=1)
            c.rect(x, top - 22, w, 8, stroke=0, fill=1)
            c.setFillColor(black)
            c.setFont("Serif-Bold", 13)
            c.drawString(x + 10, top - 16, card["heading"])

            y = top - 30
            for b in rules:
                y -= b.asc
                b.draw(c, x + 12, y)
                y -= b.desc + 7
            if exs:
                c.setFont("Serif-Bold", 10.5)
                c.setFillColor(GRAY)
                c.drawString(x + 10, y - 10, "EXAMPLES")
                c.setFillColor(black)
                y -= 20
                for b in exs:
                    y -= b.asc
                    b.draw(c, x + 12, y)
                    y -= b.desc + 7
            if tips:
                c.setFont("Serif-Bold", 10.5)
                c.setFillColor(GRAY)
                c.drawString(x + 10, y - 10, "WATCH OUT")
                c.setFillColor(black)
                y -= 20
                for b in tips:
                    y -= b.asc
                    b.draw(c, x + 12, y)
                    y -= b.desc + 7

            tops[k] = top - h - 10
        self.y = min(tops)

    def build(self):
        self.header()
        if "reminder" in self.data:
            self.reminder()
        if "intro" in self.data:
            self.intro(self.data["intro"])
        if "cards" in self.data:
            self.cheat_sheet()
        for sec in self.data.get("sections", []):
            self.section(sec)
        if "grid" in self.data:
            self.new_page()
            self.color_by_number()
        self.footer()
        self.c.save()


def main():
    src = Path(sys.argv[1])
    key = "--key" in sys.argv[2:]
    data = json.loads(src.read_text())
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{src.stem}{'-key' if key else ''}.pdf"
    Sheet(data, out, key=key).build()
    print(out)
    subprocess.run(["open", str(out)])


if __name__ == "__main__":
    main()
