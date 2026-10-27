# Daily Twenty

Daily math practice sheets, about 20 questions each, aimed at the skills a student is struggling with right now.

Each day's sheet is a printable PDF. A parent grades it and reports which question numbers were missed. The next sheet adds more practice on the skills that were missed and drops skills that have been mastered.

## How it works

1. **Skills** live in `skills.json`. Each skill has an id, a description, a status (`active` or `cleared`), and a history of results.
2. **A sheet** is a JSON file in `sheets/` named by date (`sheets/2026-10-26.json`). Each question records which skill it tests and its answer.
3. **Rendering** turns the sheet JSON into a PDF in `output/`. The PDF has a "Rules to remember" box, a worked example, and each question with space to show work and an answer line. No answer key is printed.
4. **Grading**: report the missed question numbers for that date. Each skill on the sheet gets a result entry in its history.
5. **Clearing**: a skill is cleared after 2 sheets in a row with no misses. Cleared skills still show up as an occasional review question, and a miss on review makes them active again.

## Setup

Requires Python 3 and macOS (the renderer uses the Times New Roman font in `/System/Library/Fonts/Supplemental`).

```sh
python3 -m venv .venv
.venv/bin/pip install reportlab
```

## Build a sheet

```sh
.venv/bin/python render.py sheets/2026-10-26.json
# -> output/2026-10-26.pdf
```

## Writing questions

Math expressions use a small LaTeX-like syntax:

| Syntax | Renders as |
|---|---|
| `x^{-2}` | superscript |
| `\frac{a}{b}` | stacked fraction |
| `\cdot` | multiplication dot |

Letters render italic (as variables); digits and symbols render upright. Inside JSON, backslashes are doubled: `"\\frac{1}{x^{2}}"`.

A question looks like this:

```json
{"n": 4, "skill": "neg-to-pos", "expr": "3y^{-4}", "answer": "\\frac{3}{y^{4}}"}
```

Questions are grouped into sections, and each section has one line of directions (for example, "Rewrite using only positive exponents.").

## Current topics

- Negative exponents: rewriting negative exponents as positive and positive as negative, evaluating, and simplifying with the product, quotient, and power-of-a-power rules.
- Scientific notation: converting standard form to scientific notation and back, with positive and negative powers of 10.

## License

MIT. See [LICENSE](LICENSE).
