"use client";

import { useMemo, useState } from "react";

import { ApiError, deleteTemplate, getTemplate, getTemplates, saveTemplate } from "../lib/api";
import type { StageRecord, TemplateRecord } from "../lib/types";

type TemplateDraft = {
  id: number | null;
  stage_id: string;
  name: string;
  description: string;
  markdown: string;
};

function newDraft(stageId: number | null): TemplateDraft {
  return {
    id: null,
    stage_id: stageId == null ? "" : String(stageId),
    name: "",
    description: "",
    markdown: "# New Template\n\n## Section\n\n- Question:\n\n**Answer**:\n",
  };
}

function draftFromTemplate(template: TemplateRecord): TemplateDraft {
  return {
    id: template.id,
    stage_id: String(template.stage_id),
    name: template.name,
    description: template.description || "",
    markdown: template.markdown || "",
  };
}

export function NativeTemplatesClient({
  initialTemplates,
  stages,
}: {
  initialTemplates: TemplateRecord[];
  stages: StageRecord[];
}) {
  const [templates, setTemplates] = useState(initialTemplates);
  const [selectedId, setSelectedId] = useState<number | null>(initialTemplates[0]?.id ?? null);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateRecord | null>(initialTemplates[0] ?? null);
  const [draft, setDraft] = useState<TemplateDraft>(initialTemplates[0] ? draftFromTemplate(initialTemplates[0]) : newDraft(stages[0]?.id ?? null));
  const [stageFilter, setStageFilter] = useState<string>("all");
  const [saving, setSaving] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const filteredTemplates = useMemo(() => {
    if (stageFilter === "all") return templates;
    return templates.filter((template) => String(template.stage_id) === stageFilter);
  }, [stageFilter, templates]);

  async function refreshLibrary(nextSelectedId: number | null) {
    const library = await getTemplates();
    setTemplates(library.templates);
    if (nextSelectedId == null) {
      setSelectedId(null);
      setSelectedTemplate(null);
      setDraft(newDraft(Number(stageFilter) || stages[0]?.id || null));
      return;
    }
    const detail = await getTemplate(nextSelectedId);
    setSelectedId(detail.template.id);
    setSelectedTemplate(detail.template);
    setDraft(draftFromTemplate(detail.template));
  }

  async function loadTemplate(templateId: number) {
    setLoadingDetail(true);
    setError("");
    try {
      const detail = await getTemplate(templateId);
      setSelectedId(detail.template.id);
      setSelectedTemplate(detail.template);
      setDraft(draftFromTemplate(detail.template));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to load template.");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function persistTemplate() {
    setSaving(true);
    setStatus("");
    setError("");
    try {
      const payload = {
        id: draft.id == null ? "" : String(draft.id),
        stage_id: draft.stage_id,
        name: draft.name,
        description: draft.description,
        markdown: draft.markdown,
      };
      const result = await saveTemplate(draft.id, payload);
      await refreshLibrary(result.template.id);
      setStatus("Template saved. Future reports will use the new active version while existing reports stay pinned.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to save template.");
    } finally {
      setSaving(false);
    }
  }

  async function removeTemplate(templateId: number) {
    const template = templates.find((entry) => entry.id === templateId);
    if (!template) return;
    if (!window.confirm(`Delete ${template.name}? Existing reports keep their historical template copy.`)) return;
    setStatus("");
    setError("");
    try {
      await deleteTemplate(templateId);
      const remaining = templates.filter((entry) => entry.id !== templateId);
      setTemplates(remaining);
      const next = remaining[0] ?? null;
      if (selectedId === templateId) {
        if (next) {
          await loadTemplate(next.id);
        } else {
          setSelectedId(null);
          setSelectedTemplate(null);
          setDraft(newDraft(stages[0]?.id ?? null));
        }
      }
      setStatus("Template deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to delete template.");
    }
  }

  const activeDetail = selectedTemplate;

  return (
    <>
      {status ? <section className="panel status-banner">{status}</section> : null}
      {error ? <section className="panel error-banner">{error}</section> : null}
      <section className="split native-surface-split">
        <aside className="panel">
          <div className="panel-header">
            <div>
              <h2>Template Library</h2>
              <p className="muted">
                Saving creates the next active version for that stage. Existing reports keep their pinned template snapshot.
              </p>
            </div>
          </div>
          <div className="stack-gap">
            <label className="field-block">
              <span className="field-label">Stage Filter</span>
              <select
                className="soft-input"
                value={stageFilter}
                onChange={(event) => setStageFilter(event.target.value)}
              >
                <option value="all">All stages</option>
                {stages.map((stage) => (
                  <option value={stage.id} key={stage.id}>
                    {stage.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="small-button"
              onClick={() => {
                const fallbackStageId = Number(stageFilter) || activeDetail?.stage_id || stages[0]?.id || null;
                setSelectedId(null);
                setSelectedTemplate(null);
                setDraft(newDraft(fallbackStageId));
              }}
            >
              New Template
            </button>
            <div className="card-list">
              {filteredTemplates.map((template) => (
                <article
                  className={`row-card selectable-card ${selectedId === template.id ? "selected-card" : ""}`}
                  key={template.id}
                >
                  <button type="button" className="text-button" onClick={() => void loadTemplate(template.id)}>
                    <strong>{template.name}</strong>
                    <div className="muted">
                      {template.stage_name} · v{template.version} · {template.schema?.field_count || 0} fields
                    </div>
                  </button>
                  <div className="button-row">
                    <span className={`pill ${template.is_active ? "green" : ""}`}>
                      {template.is_active ? "Active" : "Inactive"}
                    </span>
                    <button type="button" className="small-button danger" onClick={() => void removeTemplate(template.id)}>
                      Delete
                    </button>
                  </div>
                </article>
              ))}
              {!filteredTemplates.length ? <div className="empty-state">No templates match the current filter.</div> : null}
            </div>
          </div>
        </aside>
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>{draft.id ? draft.name || `Template ${draft.id}` : "New Template"}</h2>
              <p className="muted">
                {loadingDetail
                  ? "Loading template detail..."
                  : activeDetail
                    ? `${activeDetail.stage_name} · v${activeDetail.version} · ${activeDetail.schema?.section_count || 0} sections · ${activeDetail.schema?.field_count || 0} fields`
                    : "Create a new template using the exact stage and markdown contract already enforced by the backend."}
              </p>
            </div>
            <button type="button" className="small-button" disabled={saving || loadingDetail} onClick={() => void persistTemplate()}>
              {saving ? "Saving..." : "Save Template"}
            </button>
          </div>
          <div className="stack-gap">
            <div className="form-grid two-column">
              <label className="field-block">
                <span className="field-label">Stage</span>
                {draft.id ? (
                  <input className="soft-input" value={activeDetail?.stage_name || ""} disabled />
                ) : (
                  <select
                    className="soft-input"
                    value={draft.stage_id}
                    onChange={(event) => setDraft((current) => ({ ...current, stage_id: event.target.value }))}
                  >
                    <option value="">Select a stage</option>
                    {stages.map((stage) => (
                      <option value={stage.id} key={stage.id}>
                        {stage.name}
                      </option>
                    ))}
                  </select>
                )}
              </label>
              <label className="field-block">
                <span className="field-label">Name</span>
                <input
                  className="soft-input"
                  value={draft.name}
                  onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
            </div>
            <label className="field-block">
              <span className="field-label">Description</span>
              <input
                className="soft-input"
                value={draft.description}
                onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field-block">
              <span className="field-label">Markdown</span>
              <textarea
                className="soft-textarea code-textarea"
                rows={24}
                value={draft.markdown}
                onChange={(event) => setDraft((current) => ({ ...current, markdown: event.target.value }))}
              />
            </label>
            {activeDetail ? (
              <div className="split">
                <section className="panel inset-panel">
                  <h3>Schema Sections</h3>
                  <div className="card-list">
                    {activeDetail.schema.sections.map((section) => (
                      <article className="row-card compact-row-card" key={section.id}>
                        <strong>{section.title}</strong>
                        <div className="muted">
                          Level {section.level} · {section.field_ids.length} direct field ids
                        </div>
                        {section.body_markdown ? <p className="muted prewrap-text">{section.body_markdown}</p> : null}
                      </article>
                    ))}
                  </div>
                </section>
                <section className="panel inset-panel">
                  <h3>Field Snapshot</h3>
                  <div className="card-list">
                    {activeDetail.schema.fields.slice(0, 24).map((field) => (
                      <article className="row-card compact-row-card" key={field.id}>
                        <strong>{field.label}</strong>
                        <div className="muted">
                          {field.kind} · {field.section_title} · {field.id}
                        </div>
                      </article>
                    ))}
                    {activeDetail.schema.fields.length > 24 ? (
                      <div className="muted">Showing the first 24 of {activeDetail.schema.fields.length} fields.</div>
                    ) : null}
                  </div>
                </section>
              </div>
            ) : null}
          </div>
        </section>
      </section>
    </>
  );
}
