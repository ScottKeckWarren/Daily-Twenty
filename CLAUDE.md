# Daily Twenty

Daily ~20-question math practice PDFs for a 7th grade student, targeting the skills she struggles with.

## Files

- `skills.json` — every skill she's working on: `status` (active / cleared), `streak` (consecutive perfect sheets), `history` (per-sheet asked/missed counts).
- `sheets/YYYY-MM-DD.json` — the questions on each day's sheet. Each question has `n`, `skill` (id from skills.json), `expr`, and `answer`. Answers stay in the JSON only; no answer key is printed (the parent grades).
- `output/YYYY-MM-DD.pdf` — rendered sheet. Build with `.venv/bin/python render.py sheets/YYYY-MM-DD.json`.
- `render.py` — math syntax: `x^{-2}`, `\frac{a}{b}`, `\cdot`. Letters render italic. In JSON, backslashes are doubled (`\\frac`).

## Daily loop

1. **Results come in** as a list of missed question numbers for a dated sheet (e.g. "10-26: missed 4, 11, 17").
   - Look up each number's `skill` in that sheet's JSON.
   - Append `{"date", "asked", "missed": [question numbers]}` to every skill that appeared on the sheet.
   - Skill with 0 misses: `streak += 1`. Skill with any miss: `streak = 0`.
   - `streak >= 2` → `status: "cleared"`. A miss on a cleared skill's review question → back to `active`, `streak = 0`.
   - Point out patterns in the misses (e.g. coefficient moved with the variable, sign errors on negative bases).
2. **Next sheet**: ~20 questions.
   - Weight active skills by recent misses: missed skills get more questions and simpler variants first, then harder ones.
   - Cleared skills: 1–2 review questions every few sheets.
   - Don't reuse exact questions from previous sheets.
   - Group by directions (sections), easy → hard. Every question gets work space and an answer line (renderer handles this).
   - Each sheet starts with a "Rules to remember" box and one worked example relevant to the day's focus.
3. **New skills**: the parent will add new topics over time. Add them to `skills.json` with `status: "active"`, `streak: 0`.

## Preferences

- Exponent problems use both numbers and variables.
- Numeric problems say explicitly whether to "rewrite" or "evaluate".
- Simplifying covers product, quotient, and power-of-a-power rules. Power of a product (`(3x)^{-2}`) has not been introduced yet.
