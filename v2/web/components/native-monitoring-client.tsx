"use client";

import { useMemo, useState } from "react";

import { ApiError, updateMonitoringRule } from "../lib/api";
import type { MonitoringRuleRecord } from "../lib/types";

function formatDate(value: string): string {
  if (!value) return "Not checked";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString();
}

type RuleDraft = {
  current_value: string;
  notes: string;
};

export function NativeMonitoringClient({ initialRules }: { initialRules: MonitoringRuleRecord[] }) {
  const [rules, setRules] = useState(initialRules);
  const [drafts, setDrafts] = useState<Record<number, RuleDraft>>(
    Object.fromEntries(
      initialRules.map((rule) => [
        rule.id,
        {
          current_value: rule.current_value == null ? "" : String(rule.current_value),
          notes: rule.notes || "",
        },
      ]),
    ),
  );
  const [savingId, setSavingId] = useState<number | null>(null);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");

  const summary = useMemo(() => {
    const triggered = rules.filter((rule) => Boolean(rule.triggered)).length;
    return {
      total: rules.length,
      triggered,
      waiting: rules.length - triggered,
    };
  }, [rules]);

  async function saveRule(ruleId: number) {
    const draft = drafts[ruleId];
    if (!draft) return;
    setSavingId(ruleId);
    setStatus("");
    setError("");
    try {
      const result = await updateMonitoringRule(ruleId, draft);
      setRules((current) => current.map((rule) => (rule.id === ruleId ? result.rule : rule)));
      setDrafts((current) => ({
        ...current,
        [ruleId]: {
          current_value: result.rule.current_value == null ? "" : String(result.rule.current_value),
          notes: result.rule.notes || "",
        },
      }));
      setStatus(`Saved runtime update for ${result.rule.metric_name}.`);
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : "Failed to save monitoring rule.";
      setError(message);
    } finally {
      setSavingId(null);
    }
  }

  return (
    <>
      <section className="metric-grid">
        <article className="metric-card">
          <span className="eyebrow">Rules</span>
          <strong>{summary.total}</strong>
          <p className="muted">All report-generated monitoring thresholds.</p>
        </article>
        <article className="metric-card">
          <span className="eyebrow">Triggered</span>
          <strong>{summary.triggered}</strong>
          <p className="muted">Rules whose current value has crossed the saved threshold.</p>
        </article>
        <article className="metric-card">
          <span className="eyebrow">Waiting</span>
          <strong>{summary.waiting}</strong>
          <p className="muted">Rules still below or above their trigger line.</p>
        </article>
      </section>
      {status ? <section className="panel status-banner">{status}</section> : null}
      {error ? <section className="panel error-banner">{error}</section> : null}
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Objective Rules</h2>
            <p className="muted">
              Update only runtime values and notes here. Structural rule fields still belong to the originating report.
            </p>
          </div>
        </div>
        {rules.length ? (
          <div className="table-wrap">
            <table className="native-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Metric</th>
                  <th>Rule</th>
                  <th>Runtime Updates</th>
                  <th>Status</th>
                  <th>Source</th>
                  <th>Last Checked</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => {
                  const draft = drafts[rule.id] || { current_value: "", notes: "" };
                  return (
                    <tr key={rule.id}>
                      <td>
                        <strong>{rule.ticker}</strong>
                        <div className="muted">{rule.company_name}</div>
                      </td>
                      <td>{rule.metric_name}</td>
                      <td>
                        {rule.comparator} {rule.threshold_value ?? ""} {rule.unit || ""}
                      </td>
                      <td>
                        <div className="rule-edit-grid">
                          <input
                            className="soft-input"
                            type="number"
                            step="any"
                            value={draft.current_value}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [rule.id]: {
                                  ...draft,
                                  current_value: event.target.value,
                                },
                              }))
                            }
                          />
                          <textarea
                            className="soft-textarea"
                            rows={3}
                            value={draft.notes}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [rule.id]: {
                                  ...draft,
                                  notes: event.target.value,
                                },
                              }))
                            }
                          />
                          <button
                            className="small-button"
                            type="button"
                            disabled={savingId === rule.id}
                            onClick={() => void saveRule(rule.id)}
                          >
                            {savingId === rule.id ? "Saving..." : "Save"}
                          </button>
                        </div>
                      </td>
                      <td>
                        <span className={`pill ${Boolean(rule.triggered) ? "green" : "amber"}`}>
                          {Boolean(rule.triggered) ? "Triggered" : "Waiting"}
                        </span>
                      </td>
                      <td>{rule.source || <span className="muted">Report objective rule</span>}</td>
                      <td>{formatDate(rule.last_checked_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">No monitoring rules have been created yet.</div>
        )}
      </section>
    </>
  );
}
