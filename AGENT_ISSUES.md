# Agent Issues File

Purpose: a short shared log for agents to record app bugs, workflow blockers, and workarounds.

Rules:

- append newest entries at the top under `## Log`
- keep entries concise
- log the issue even if you solved it
- if you used a workaround, write it down

## Template

```md
### YYYY-MM-DD - Company / Report / Stage
- Issue: what went wrong
- Status: Open | Solved | Workaround
- Resolution: how it was fixed or worked around
- Follow-up: what still needs attention, if anything
```

## Log

### 2026-04-19 - Laureate / Valuation and Position Size / Broken select option
- Issue: The valuation template option for `Cyclical / commodity / asset-heavy business - Usually inappropriate as primary` is split into two malformed choices, `Peak-year P` and `E or peak margin DCF`, instead of one valid label.
- Status: Workaround
- Resolution: Completed the report by selecting the broken `Peak-year P` fragment so the saved response would pass schema validation.
- Follow-up: Fix the template option text so the full label is stored as one selectable value.

### 2026-04-19 - Laureate / Financial Underwriting / Template field-id collision
- Issue: Several long-label rows in `Part VII. Accounting And Red-Flag Log` of the financial-underwriting template share collided/truncated field IDs, so different controls map to the same saved response key.
- Status: Workaround
- Resolution: Completed the report by using the shared response key, then added one shared field note for each collided key so completion and finalize would pass. Also had to target `Liquidity` by occurrence because `Liquidity sources` and `Liquidity` share a prefix.
- Follow-up: Regenerate unique field IDs for the affected template rows so status, severity, evidence grade, source, and notes do not overwrite each other.

### 2026-04-18 - Butterfly Network / Financial Underwriting / UI visibility
- Issue: Completed underwriting reports could look broken because the editor always rendered the full pinned template, leaving sparse-but-saved reports mostly blank on screen.
- Status: Solved
- Resolution: Added an answered-only display mode for completed questionnaire reports, surfaced coverage stats in the header, and defaulted completed reports into the answered-only view so saved underwriting is visible first.
- Follow-up: Completion rules still allow sparse later-stage reports to be marked complete; if that becomes a workflow problem, tighten backend completion criteria separately from the UI.
