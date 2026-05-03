# Stock Picking Funnel

Local v0 web app for managing a value-investing research funnel. It stores companies, reports, editable report templates, uploaded documents, watchlist/archive summaries, and objective monitoring rules in a local SQLite database.

Agent entrypoint:

- Start new agents at [AGENT_RUNBOOK.md](/Users/Diego/Everything/Projectos_Personales/Value_Investing/stock-picking-funnel/AGENT_RUNBOOK.md:1)

## Stack Choice

This v0 is intentionally dependency-light:

- Backend: Python standard library HTTP server.
- Database: SQLite file at `var/funnel.db`.
- Frontend: vanilla HTML, CSS, and JavaScript.
- Tests: Python `unittest`.

This is the right shape for a private research workflow while the data model is still changing. It avoids a framework/database setup tax, keeps every record local, and still gives you a real relational schema. When the workflow stabilizes or multiple users need access, the next step should be PostgreSQL plus a framework such as Django, FastAPI, or Next.js.

## Database Setup

For v0, you do not need to install a database server. SQLite is included with Python, and the app creates `var/funnel.db` automatically on first run.

Install required:

- Python 3.11 or newer.

Optional later production install:

- PostgreSQL, if you want multi-user access, hosted backups, stronger concurrent writes, or remote deployment.

## Run

From this folder:

```bash
python3 app.py
```

Then open:

```text
http://127.0.0.1:8011
```

Optional environment variables:

```bash
FUNNEL_PORT=8020 python3 app.py
FUNNEL_DB_PATH=/absolute/path/to/funnel.db python3 app.py
FUNNEL_UPLOAD_DIR=/absolute/path/to/uploads python3 app.py
FUNNEL_SEED_CONFIG=/absolute/path/to/default_stages.json python3 app.py
```

## Test

```bash
python3 -m unittest discover -s tests -v
```

The API tests start a temporary localhost server. If your execution environment blocks local socket binding, run the test command in a normal terminal.

## What Is Configurable

The app does not hard-code the funnel stage list or report form fields into the UI.

- Stages and initial template sources are defined in `config/default_stages.json`.
- The main underwriting questionnaires are seeded from `../Source_Candidates/approved_version/`.
- Data collection, valuation, and execution starter templates live in `config/templates/`.
- Once seeded, templates are editable directly in the web app. Saving a template regenerates its fillable fields.

Template-structure protection:

- If startup seeding would change stages/templates, the app now asks for two warning confirmations before writing anything.
- Before seed/import changes are applied, the current report structure is backed up into `var/report_structure_backups/`.
- The database seed only inserts templates when a stage has no active template, so edits made through the app are not overwritten on restart.

## Current v0 Behavior

- Add companies to the untouched company pool.
- Start a report to move a company into the active funnel.
- Fill text responses, objective metrics, section quality scores, and data quality ratings.
- Save a report result as `Proceed to Next Step`, `Watchlist`, or `Archive`.
- Move companies automatically based on the report result.
- Show watchlist conditions and archive red flags directly in their tabs.
- Upload any file type against a company or a specific report.
- Create objective monitoring rules from report decisions.
- Update current values in the Monitoring tab and trigger alerts when thresholds are met.

Live market-data ingestion is not connected in v0 because no provider/API key was specified. The app has provider-neutral rule storage and evaluation, so a later data-feed job can update `monitoring_rules.current_value` without changing the UI flow.
