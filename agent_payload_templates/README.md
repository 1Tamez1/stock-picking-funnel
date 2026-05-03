# Agent Payload Templates

These files are starter PATCH payload snapshots for the current active live report templates.

For hosted/authenticated use, export these first:

```bash
export FUNNEL_API_URL="${FUNNEL_API_URL:-http://127.0.0.1:8211}"
export FUNNEL_API_TOKEN="${FUNNEL_API_TOKEN:-}"
export AUTH_HEADER="Authorization: Bearer ${FUNNEL_API_TOKEN}"
```

Issue or rotate the owner bearer token with:

```bash
python v2/scripts/manage_owner_tokens.py issue \
  --label "Runbook Token" \
  --expires-in-days 30 \
  --scopes read,write_sources,write_reports
```

Verify that token against the hosted stack with:

```bash
python v2/scripts/verify_owner_token.py \
  --base-url "${FUNNEL_API_URL}" \
  --api-token "${FUNNEL_API_TOKEN}"
```

When validating the whole hosted stack instead of a single token, use:

```bash
./v2/deploy/validate.sh ./v2/deploy/.env.hosted
```

Use them as a fallback scaffold only. The canonical workflow is:

1. open or create the live report
2. save the live report JSON to a temporary bootstrap file
3. create a standardized workspace folder under `/tmp/report_workspaces/<company>__<stage>__<timestamp>/`
4. fill one `sections/*.section.template.json` file at a time
5. preview and PATCH that section
6. re-read that section and verify the section revision
7. run report-level completion preview
8. finalize only after approval

Why these files still exist:

- they let an agent start quickly when the generator cannot hit the live app directly
- they provide a stable snapshot of the current stage-specific payload shape
- they reduce ad hoc JSON assembly in the shell
- they preserve the old full-report patch contract as compatibility while section modules become the preferred machine contract

Important:

- these files can go stale when templates change
- later-stage starter files include inherited-section fields because some of them are editable handoff prompts
- always compare against `report.agent_contract.readonly_field_ids` before PATCHing and remove only the live read-only field IDs
- some templates can contain repeated checkbox entries that collapse to fewer unique PATCH keys than the raw template `field_count`; see `manifest.json`
- once a report workspace folder exists, keep that report's temp files inside it instead of scattering files directly under `/tmp`
- generated report workspaces include `sections/*.section.template.json`; those modular files are safer for agents than one giant full-report patch because each section can be saved and verified independently
- the committed `manifest.json` records the default V2 API base; override it in live use with `FUNNEL_API_URL`
