# Agent Runbook

Purpose: this is the first document an agent should read before working on any company or report in this app.

Use this runbook to understand:

- what the app is
- how the data is structured
- how to complete a given report for a given company
- where to get information
- how to upload and cite evidence
- how to troubleshoot common failures
- how to log issues in the shared issues file

## Hosted Auth Setup

For hosted use, export these before running any curl examples:

```bash
export FUNNEL_API_URL="${FUNNEL_API_URL:-http://127.0.0.1:8211}"
export FUNNEL_API_TOKEN="${FUNNEL_API_TOKEN:-}"
export AUTH_HEADER="Authorization: Bearer ${FUNNEL_API_TOKEN}"
```

Browser use can still go through `/login`.
CLI, agent, and runbook flows should use the bearer token header on protected `/api/*` routes.

Useful hosted helpers now live under `v2/scripts/`:

- `bootstrap_owner.py`
- `manage_owner_tokens.py`
- `verify_owner_token.py`
- `run_hosted_smoke.py`
- `run_hosted_validation.py`

For a full live-stack proof run on the Docker/Caddy/Postgres/MinIO stack, use:

- `v2/deploy/up.sh`
- `v2/deploy/validate.sh`
- `v2/scripts/rehearse_cutover.sh`
- `v2/scripts/verify_restore.sh`

## If You Remember Only Ten Things

1. The live report at `GET /api/reports/:id` is the source of truth.
2. Do not use company report summaries as if they were full reports. Open the actual report.
3. Do not use `GET /api/bootstrap` to understand templates. Bootstrap no longer includes templates.
4. For report work, read `agent_contract`, `completion`, `workflow.latest_upstream_report`, `suggested_sources`, and `company_sources` first.
5. Reuse existing company sources before creating new ones.
6. Use `POST /api/report-sources` or the report source dialog for citable evidence. Use `POST /api/documents` only for company-level uploads that are not yet report sources.
7. Later-stage inherited fields are intentionally read-only. Annotate them with `field_sources` and `field_notes`; do not try to overwrite them.
8. Document normalization is asynchronous now. New uploads often start as `pending`; use `GET /api/documents/:id/status` instead of assuming the normalized view is ready immediately.
9. URL-only sources are degraded. If you save one, you must acknowledge the snapshot guidance and write why it is still `link_only`. Cited `link_only`, `pending`, and `failed` sources block finalization.
10. If you hit a bug, blocker, or strange behavior, add a short entry to [AGENT_ISSUES.md](AGENT_ISSUES.md) before you leave.

## What This App Is

This app is a local value-investing research funnel.

It tracks:

- companies
- reports for each funnel stage
- editable templates
- uploaded documents
- report sources that can be cited in answers
- company-wide reusable sources
- watchlist and archive outcomes
- objective monitoring rules

The main goal of an agent is usually:

- take one company
- open one report
- gather or reuse evidence
- fill the report correctly
- leave a clean handoff for the next stage

## Mental Model

Think in these objects:

- `Company`: the entity being researched. It has a bucket and a current funnel position.
- `Report`: one stage-specific research artifact for one company.
- `Template`: the questionnaire shape for new reports in a stage.
- `Document`: a stored file upload.
- `Report Source`: a citable evidence record, optionally linked to a document and/or URL.
- `Company Source`: the reusable library view across all report sources for the company.
- `Monitoring Rule`: an objective threshold tracked after watchlist or later-stage work.

Important consequences:

- Existing reports are pinned to their template snapshot.
- Editing a template creates a new active version for future reports.
- Company pages now show report summaries only, not full report bodies.
- The full working payload is still `GET /api/reports/:id`.

## What Lives Where

Use these endpoints as your map:

All API responses now include `X-Funnel-Instance-Id` and `X-Funnel-Request-Id`.
JSON error bodies include `code` and `request_id`.

- `GET /api/health`
  Returns minimal liveness only.

- `GET /api/health/runtime`
  Returns owner-protected runtime metadata such as instance, database, upload/storage, and worker/job health.

- `GET /api/bootstrap`
  Returns dashboard, stages, buckets, and report actions.
  It does not return templates.

- `GET /api/companies/:id`
  Returns company detail, report summaries, documents, company sources, and monitoring rules.
  Use this to orient yourself, not to reason from report content.

- `GET /api/reports/:id`
  Returns the full report working payload.
  This is the main agent entrypoint for actual report completion.

- `GET /api/templates`
  Returns template library summaries only.

- `GET /api/templates/:id`
  Returns full template detail, including markdown.

- `POST /api/report-sources`
- `PATCH /api/report-sources/:id`
- `DELETE /api/report-sources/:id`
  Use these for citable evidence attached to a report.

- `POST /api/documents`
  Use this for company-level uploads that are not yet being cited in a report.

- `GET /api/documents/:id/status`
  Use this lightweight endpoint to check whether normalization is still `pending`, became `ready`, is only `limited`, or failed.

- `GET /api/documents/:id/normalized`
  Use this to read the LLM-friendly normalized text when available.

- `GET /api/documents/:id/download`
  Use this to inspect the original artifact when normalization is weak, partial, or missing.

## Minimal Reading Path

Read in this order:

1. This file.
2. The target report in the app or via `GET /api/reports/:id`.
3. `report.agent_contract`.
4. `report.completion`.
5. `report.workflow.latest_upstream_report`.
6. The latest upstream full report itself, if the stage is later than Data Collection.
7. `report.suggested_sources`.
8. `report.company_sources`.

Only read code if you are blocked or debugging behavior.

## What The Live Report Already Gives You

When you open a report, you already get the working context you need:

- `template.schema`
- `agent_contract`
- `completion`
- `responses`
- `metrics`
- `section_ratings`
- `data_quality`
- `field_sources`
- `field_notes`
- `sources`
- `suggested_sources`
- `company_sources`
- `workflow`
- source durability metadata such as `capture_state`, `capture_error`, `link_only_reason`, and `snapshot_guidance_acknowledged`
- auto-inherited upstream fields

That is the main working surface. Start there, not in repo markdown.

## Where To Get Information

Use this priority order:

1. The current report payload.
2. The latest upstream full report.
3. The report's `suggested_sources`.
4. The rest of `company_sources`.
5. Company documents and normalized document views.
6. New external evidence only if the current library is insufficient.
7. Repo code only if app behavior is unclear or broken.

When you need template details:

- use the report's `template.schema` for active report filling
- use `GET /api/templates/:id` only if you are editing or debugging template structure

When you need upstream context:

- use `workflow.latest_upstream_report` to identify the main upstream handoff
- open that report directly
- do not rely on `company.reports` summaries for detailed reasoning

## Universal Report Procedure

Do this for every report:

1. Open the report.
2. Identify `company_id`, `stage_key`, `template.schema`, and `agent_contract.goal`.
3. Read `completion` and write down what is still missing.
4. Read `workflow.latest_upstream_report`.
5. If there is an upstream report, open it and read the decision, summary, unresolved issues, and one-page conclusion.
6. Review auto-inherited fields in the current report.
7. Review `suggested_sources`.
8. Reuse existing evidence first.
9. Add new sources only when the existing source library cannot support the answer.
10. Fill every non-exempt editable field, not just the obvious stage-gate outputs.
11. Link evidence to every covered answer through `field_sources`. A field-level link or a section-level link both count.
12. Use `field_exceptions` only after investigation when a field cannot be answered cleanly. Every exception still requires a field note and a source.
13. Use `field_notes` for caveats, uncertainty, and audit trail. Notes are required for structured answers such as selects, dates, metrics, numbers, and structured datapoints; they stay optional for narrative text unless you are documenting an exception.
14. Before finalizing, confirm the cited source set is durable enough: cited `link_only`, `pending`, and `failed` sources block finalize; cited `limited` sources are allowed but should be checked against the original artifact.
15. Fill the decision-specific follow-up section for the chosen result, then finalize.
16. If a normalized source is still `pending`, wait and re-check `GET /api/documents/:id/status` instead of repeatedly reopening the full report or company page.
17. Re-open mentally or visually and confirm the report is complete enough for the next human or agent.
18. If you hit a bug or suspicious behavior, log it in [AGENT_ISSUES.md](AGENT_ISSUES.md).

## Canonical Temp-File Workflow

Use one file-based workflow for every report. Do not hand-build giant inline JSON payloads in the shell.

All report temp files must live inside one standardized workspace folder:

`/tmp/report_workspaces/<company-slug>__<stage-key>__YYYYMMDD-HHMMSS>/`

Example:

`/tmp/report_workspaces/ares-management-corporation-class-a-common-stock__business-underwriting__20260418-221530/`

Once that folder exists, keep the report's temp files there. Do not scatter report temp files directly under `/tmp`.

### A. Create the report when needed

If the report does not exist yet, create it first:

```bash
curl -sS -H "$AUTH_HEADER" -X POST \
  -H 'Content-Type: application/json' \
  --data '{"company_id":1374,"stage_id":2}' \
  "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/reports"
```

Use `stage_id` from `GET /api/bootstrap`.

### B. Generate the patch template from the live report

Canonical path:

Save the live report first, then create the standardized report workspace from that file:

```bash
curl -sS -H "$AUTH_HEADER" "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/reports/61" -o /tmp/report-61.bootstrap.json
WORKDIR=$(node tools/generate_report_payload_templates.mjs \
  --report-file /tmp/report-61.bootstrap.json \
  --workspace-root /tmp/report_workspaces)
```

The command prints the created workspace folder path.

This creates a standardized folder named from:

- company
- report stage
- current date and time

Inside that folder, the generator writes:

- `report.live.json`
- `report.patch.template.json`
- `report.patch.json`
- `workspace.json`

Later, the verification step writes `report.verify.json` into the same folder.

The generated `report.patch.template.json` already:

- uses the current pinned live schema
- splits `responses` from `metrics`
- excludes current read-only inherited field IDs
- carries the current `expected_revision`

### C. Fill the patch file

Edit `$WORKDIR/report.patch.json` and fill:

- `expected_revision`
  Keep the live report revision currently returned by `GET /api/reports/:id`.
- `responses`
  Text, select, textarea, and date answers.
- `metrics`
  Numeric answers only.
- `field_sources`
  Add a source object for every covered field:
  - `source_ids`: list of reusable source IDs
  - `citation`: plain-text citation summary
- `field_notes`
  Required for every non-text structured answer and for any text/textarea field that is presented as a structured datapoint in the live schema. Narrative text stays optional unless you are documenting an exception.
- `field_exceptions`
  Use only for explicit `unknown`, `not_disclosed`, or `not_applicable` coverage after investigation.

Safe default starter shape:

```json
{
  "expected_revision": 1,
  "finalize": false,
  "responses": {},
  "metrics": {},
  "field_sources": {},
  "field_notes": {},
  "field_exceptions": {}
}
```

Do not add inherited read-only fields back into the patch file.

If you create any additional report-scoped temp files, store them in the same workspace folder.

### D. Save the report

Optional manual completion preview before saving:

```bash
curl -sS -H "$AUTH_HEADER" -X POST \
  -H 'Content-Type: application/json' \
  --data-binary @"$WORKDIR/report.patch.json" \
  "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/reports/61/preview"
```

This runs the same synchronization and completion logic as save/finalize, but does not persist anything.

Draft save:

```bash
curl -sS -H "$AUTH_HEADER" -X PATCH \
  -H 'Content-Type: application/json' \
  --data-binary @"$WORKDIR/report.patch.json" \
  "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/reports/61"
```

Final save:

- fill the decision field in `responses`
- keep `result`, `summary`, `watchlist_conditions`, `archive_red_flags`, `next_action`, and `review_date` aligned with the report content; the backend now synchronizes these summary fields from the decision sections on save
- if the chosen result is `Watchlist` or `Archive`, include `review_date`
- if the chosen result is `Watchlist`, include at least one `watchlist_objective_rule` so a monitoring rule is created
- set `finalize` to `true` only on the last save

### E. Verify after every save

Always re-open the live report and verify:

```bash
curl -sS -H "$AUTH_HEADER" "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/reports/61" -o "$WORKDIR/report.verify.json"
```

Check:

- `report.agent_contract.completion.status`
- `missing_field_ids`
- `missing_source_links`
- `decision_requirements`
- `warnings`
- `readonly_field_ids`

If `expected_revision` is stale, reload the report, regenerate the patch template, and retry.

## Starter Payload Files

Committed stage starter files live in `agent_payload_templates/`.

Use them only as stage snapshots or fallback scaffolds. The report-specific generator above is the canonical path because starter files can go stale when templates change and later-stage starter files include inherited fields that may be read-only in the live report.

Available files:

- `agent_payload_templates/00-create-report.template.json`
- `agent_payload_templates/01-data_collection.patch.template.json`
- `agent_payload_templates/02-screening.patch.template.json`
- `agent_payload_templates/03-business_underwriting.patch.template.json`
- `agent_payload_templates/04-management_underwriting.patch.template.json`
- `agent_payload_templates/05-financial_underwriting.patch.template.json`
- `agent_payload_templates/06-valuation_position_size.patch.template.json`
- `agent_payload_templates/07-execution_rules.patch.template.json`

Recommended fallback usage:

```bash
WORKDIR=/tmp/report_workspaces/ares-management-corporation-class-a-common-stock__business-underwriting__20260418-221530
mkdir -p "$WORKDIR"
curl -sS -H "$AUTH_HEADER" "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/reports/61" -o "$WORKDIR/report.live.json"
cp agent_payload_templates/03-business_underwriting.patch.template.json "$WORKDIR/report.patch.template.json"
cp agent_payload_templates/03-business_underwriting.patch.template.json "$WORKDIR/report.patch.json"
```

Then compare the copied file against:

- `report.template.schema`
- `report.agent_contract.readonly_field_ids`
- `report.revision`

Before saving:

- remove any field IDs that the live report marks read-only
- keep editable inherited-section prompts that are not listed in `readonly_field_ids`
- replace the placeholder `expected_revision`
- keep every other report temp file for that report in the same workspace folder

## Refreshing Starter Payload Files

To refresh the committed starter files from the current live app templates:

```bash
curl -sS -H "$AUTH_HEADER" "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/templates" -o /tmp/live_templates.json
curl -sS -H "$AUTH_HEADER" "${FUNNEL_API_URL:-http://127.0.0.1:8211}/api/bootstrap" -o /tmp/live_bootstrap.json
node tools/generate_report_payload_templates.mjs \
  --all-stages \
  --templates-file /tmp/live_templates.json \
  --bootstrap-file /tmp/live_bootstrap.json
```

This rewrites `agent_payload_templates/` from the active template library and updates the manifest file there.

## Source Workflow

Always use this order:

1. `suggested_sources`
2. the rest of `company_sources`
3. create a new source only if needed

Do not duplicate a source just because you are in a later stage.

If a source already exists in the company library:

- reuse its source ID in `field_sources`
- add a new note only if your stage-specific use needs extra context

## Upload And Source Rules

Use the right upload path:

- Use `POST /api/report-sources` or the report source dialog when the evidence should be cited in the report.
- Use `POST /api/documents` only when you are storing company material that is not yet a report source.

When creating a report source, include as much of this as you can:

- `title`
- `source_type`
- `evidence_grade`
- `confidence`
- `url`
- `citation`
- `notes`
- `tags`
- file upload, if a file exists

For website-only evidence:

- do not save a bare URL and stop
- save the live URL
- also save a durable artifact when possible
- if you still save it as URL-only, you must acknowledge the snapshot guidance and write `link_only_reason`
- a cited URL-only source will block finalization until a durable snapshot is uploaded

Preferred website snapshot formats:

- `text/html` when structure matters
- `.md` or `.txt` when you already extracted the visible text
- `.csv` or spreadsheet format when the page is table-heavy

Source quality meanings:

- `Ready`: stored artifact plus usable normalized LLM text
- `Pending`: stored artifact saved, but normalization is still running
- `Limited`: stored artifact exists, but normalized text is weak or partial
- `Link Only`: URL exists without durable stored artifact
- `Failed`: artifact exists but normalization failed or the source is malformed

Source API notes:

- `capture_state` is the durable state to watch for report sources: `ready`, `pending`, `limited`, `link_only`, or `failed`
- `capture_error` explains failed stored-artifact sources
- `link_only_reason` explains why a source is still degraded
- `snapshot_guidance_acknowledged` records that the uploader read the snapshot guidance before saving a degraded URL-only source

## How To Fill Reports Correctly

General rules:

- Use the live schema from the report, not a repo template file.
- Cover every non-exempt editable field before finalizing.
- Link evidence to every covered answer.
- Preserve uncertainty explicitly instead of hiding it.
- Use explicit field exceptions only when a note and source can justify the missing answer.
- Do not solve downstream-stage questions too early.

Use these fields correctly:

- `responses`: text, categorical, date, and general answer fields
- `metrics`: numeric fields
- `field_sources`: evidence links for answers
- `field_notes`: caveats, context, or nuance. Required for structured answers; optional for narrative text unless an exception is used.
- `field_exceptions`: explicit unknown / not disclosed / not applicable coverage states
- `section_ratings`: section-level scoring where used
- `data_quality`: section-level evidence quality where used

For inherited fields:

- they may be visible inside `responses`
- they are read-only by design
- you may still annotate them with `field_sources` and `field_notes`

For saves through the API:

- always send `expected_revision`
- send `finalize: true` only on the last save, after the report passes exhaustive completion
- if you get a revision conflict, reload the latest report and retry
- expect structured JSON errors with `code` and `request_id`
- every API response now includes `X-Funnel-Instance-Id` and `X-Funnel-Request-Id`

## Stage Guide

The funnel stages are:

1. Data Collection
2. Screening
3. Business Underwriting
4. Management Underwriting
5. Financial Underwriting
6. Valuation and Position Size
7. Execution Rules

### 1. Data Collection

Primary goal:

Build a reusable evidence pack that lets Screening start with real source coverage instead of searching from zero.

Focus on:

- basic inputs
- source coverage
- anchor documents
- a clean Screening handoff

Finish when:

- the core source pack exists
- the important sources are stored as report sources, not just loose documents
- the report clearly says what Screening should read first

### 2. Screening

Primary goal:

Decide whether the company deserves Business Underwriting, Watchlist, or Archive.

Focus on:

- fast kill items
- business quality
- fragility
- rough valuation
- one-page conclusion
- preserved downstream issues

Finish when:

- required Screening outputs are complete
- the chosen decision is explicit
- the handoff makes later work easier instead of harder

### 3. Business Underwriting

Primary goal:

Test whether the business itself is good enough to justify Management Underwriting.

Focus on:

- the claim inherited from Screening
- moat and competitive advantage
- unit economics
- capital intensity
- reinvestment runway
- fragility
- one-page business conclusion

Finish when:

- the business case is actually underwritten
- unresolved business questions are explicit
- Management Underwriting receives a clean handoff

### 4. Management Underwriting

Primary goal:

Judge whether management behavior deserves Financial Underwriting.

Focus on:

- candor
- incentives
- capital allocation
- buybacks and issuance
- governance and control risk
- succession depth
- one-page management conclusion

Finish when:

- the management decision is explicit
- the critical evidence is linked
- Financial Underwriting can see exactly what numerical questions remain

### 5. Financial Underwriting

Primary goal:

Normalize economics, test resilience, and decide whether valuation work is justified.

Focus on:

- returns on capital
- owner earnings normalization
- cash conversion
- balance-sheet resilience
- accounting quality
- main normalization issue
- one-page financial conclusion

Finish when:

- the financial picture is clear enough for valuation
- accounting and balance-sheet risks are explicit
- valuation questions are parked, not prematurely solved

### 6. Valuation And Position Size

Primary goal:

Turn the underwritten business into a disciplined value range, expected return view, and position-sizing decision.

Focus on:

- normalized earnings or cash-flow base
- value range and assumptions
- downside and failure cases
- expected return
- sizing logic
- return-to-underwriting triggers if valuation depends on unproven claims

Finish when:

- the value range is explicit
- the position-size logic is explicit
- the report clearly says what price or evidence conditions would justify action or delay

### 7. Execution Rules

Primary goal:

Translate the full research stack into concrete action rules, no-buy conditions, and monitoring logic.

Focus on:

- trigger conditions
- disconfirming evidence
- no-buy rules
- re-underwrite conditions
- monitoring handoff

Finish when:

- another person could execute the plan without guessing
- the action rules match the underwriting work
- watchlist or monitoring implications are clear

## What To Avoid

- Do not treat `GET /api/bootstrap` as a template source.
- Do not use company report summaries as substitute full reports.
- Do not create duplicate sources that already exist in `suggested_sources` or `company_sources`.
- Do not overwrite inherited fields manually.
- Do not use repo markdown as the active questionnaire when the live report differs.
- Do not stop at a bare URL for a reusable website source.
- Do not fill a final decision without also filling the matching decision-specific follow-up fields.
- Do not leave the next stage to rediscover the same unresolved issue you already saw.

## Troubleshooting

If something feels wrong, check these first.

### I cannot find full upstream context

Cause:

- you are looking at `company.reports`, which are summaries only

Fix:

- use `workflow.latest_upstream_report`
- open the real upstream report via `GET /api/reports/:id`

### The template library is missing from bootstrap

Cause:

- this is expected now

Fix:

- use `GET /api/templates` for summaries
- use `GET /api/templates/:id` for full template detail

### I cannot edit an inherited field

Cause:

- inherited fields are read-only by design

Fix:

- annotate with `field_sources` or `field_notes`
- if the inherited value itself is wrong, fix the upstream report or log the issue

### I have a document but cannot cite it cleanly

Cause:

- documents are storage objects, not automatically report sources

Fix:

- create or update a report source that links the document
- then cite the report source in `field_sources`

### The normalized LLM view is still pending

Cause:

- document normalization now runs in a background worker after upload

Fix:

- check `GET /api/documents/:id/status`
- wait for `pending` to become `ready`, `limited`, or `failed`
- do not keep polling the full report or company payload just to watch normalization

### The normalized LLM view is weak or missing

Cause:

- normalization may still be pending, limited, or failed

Fix:

- if it is pending, check `GET /api/documents/:id/status` again later
- open the original file
- verify manually
- if needed, upload a cleaner artifact
- log recurring normalization failures in [AGENT_ISSUES.md](AGENT_ISSUES.md)

### A URL-only source is blocking finalize

Cause:

- cited `link_only` sources are degraded and no longer count as final-stage durable evidence

Fix:

- upload a durable snapshot into that source, or create a replacement source with a stored artifact
- keep `link_only_reason` only as a draft-state explanation, not as a substitute for the snapshot

### I saved but the report no longer matches my local draft

Cause:

- revision conflict or concurrent change

Fix:

- reload the latest report
- use the newest `revision`
- retry with the current payload

### The company did not move where I expected

Cause:

- the result may be incomplete, invalid for the stage, or missing required follow-up context

Fix:

- confirm the final result
- confirm decision-specific fields are filled
- save again
- if behavior still looks wrong, log it

### I think the app behavior is a bug

Do this:

1. confirm you are using the live report, not a summary
2. confirm the issue still reproduces after reload
3. log it in [AGENT_ISSUES.md](AGENT_ISSUES.md)
4. only then read code if needed

## Code Reading Path If Blocked

Do not start by reading the whole repo. Read only what matches your problem.

Start here:

1. [README.md](README.md)
2. [funnel_app/db.py](funnel_app/db.py)
3. [funnel_app/server.py](funnel_app/server.py)
4. [static/app.js](static/app.js)
5. [config/default_stages.json](config/default_stages.json)

Useful areas:

- report assembly and inheritance logic in `funnel_app/db.py`
- API routing in `funnel_app/server.py`
- runtime and worker lifecycle in `funnel_app/runtime.py`
- source dialog and report editor behavior in `static/app.js`

## Issues File: Required

Agents must write issues to [AGENT_ISSUES.md](AGENT_ISSUES.md).

Write an issue entry when:

- you hit a real bug
- the app behaves differently than the runbook says
- a save or upload flow fails unexpectedly
- normalization is consistently broken for a source type
- a template or inheritance behavior looks wrong
- you had to invent a workaround

Do not write essays. Use the concise template from the issues file.

Minimum rule:

- if you were blocked, confused, or had to work around app behavior, add an entry

## One-Line Operating Rule

Open the live report, read the latest upstream handoff, reuse the best existing sources, upload durable snapshots instead of stopping at bare URLs, cover every non-exempt field with answers or justified exceptions, finalize only after the cited evidence is durable enough for the next stage, and leave a short issue note when the app gets in your way.
