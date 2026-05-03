#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { execFileSync } from "node:child_process";

const DEFAULT_API_URL = process.env.FUNNEL_API_URL || "http://127.0.0.1:8211";
const DEFAULT_STAGE_DIR = "agent_payload_templates";
const DEFAULT_WORKSPACE_ROOT = "/tmp/report_workspaces";

function usage() {
  return `
Usage:
  node tools/generate_report_payload_templates.mjs --report-file /path/to/report.json [--out /tmp/report.patch.template.json]
  node tools/generate_report_payload_templates.mjs --report-file /path/to/report.json --workspace-root ${DEFAULT_WORKSPACE_ROOT}
  node tools/generate_report_payload_templates.mjs --all-stages --templates-file /tmp/live_templates.json --bootstrap-file /tmp/live_bootstrap.json
  node tools/generate_report_payload_templates.mjs --report-id <id> [--out /tmp/report-<id>.patch.template.json]

Options:
  --api-url <url>         Base API URL. Default: ${DEFAULT_API_URL}
  --out <path>            Output file for --report-id / --report-file mode.
  --stage-dir <path>      Output directory for --all-stages mode. Default: ${DEFAULT_STAGE_DIR}
  --workspace-root <path> Create a standardized report workspace folder under this root.
  --templates-file <path> Use a saved /api/templates payload instead of curling the live app.
  --bootstrap-file <path> Use a saved /api/bootstrap payload instead of curling the live app.

Notes:
  File-fed mode is the safest path in sandboxed agent sessions.
`.trim();
}

function parseArgs(argv) {
  const args = {
    apiUrl: DEFAULT_API_URL,
    stageDir: DEFAULT_STAGE_DIR,
    workspaceRoot: "",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    const next = argv[i + 1];
    if (token === "--all-stages") args.allStages = true;
    else if (token === "--report-id") {
      args.reportId = Number(next);
      i += 1;
    } else if (token === "--report-file") {
      args.reportFile = next;
      i += 1;
    } else if (token === "--out") {
      args.out = next;
      i += 1;
    } else if (token === "--stage-dir") {
      args.stageDir = next;
      i += 1;
    } else if (token === "--workspace-root") {
      args.workspaceRoot = next;
      i += 1;
    } else if (token === "--api-url") {
      args.apiUrl = next;
      i += 1;
    } else if (token === "--templates-file") {
      args.templatesFile = next;
      i += 1;
    } else if (token === "--bootstrap-file") {
      args.bootstrapFile = next;
      i += 1;
    } else if (token === "--help" || token === "-h") {
      args.help = true;
    } else {
      throw new Error(`Unknown argument: ${token}`);
    }
  }
  return args;
}

function readJsonViaCurl(apiUrl, apiPath) {
  const stdout = execFileSync("curl", ["-sS", `${apiUrl}${apiPath}`], { encoding: "utf8" });
  return JSON.parse(stdout);
}

async function readJsonFile(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

function isScalarField(field) {
  return !["metric", "number"].includes(String(field.kind || ""));
}

function sortedFields(fields) {
  return [...(fields || [])].sort((a, b) => Number(a.ordinal || 0) - Number(b.ordinal || 0));
}

function buildPatchTemplate(fields, readonlyIds = new Set()) {
  const responses = {};
  const metrics = {};
  for (const field of sortedFields(fields)) {
    if (readonlyIds.has(field.id)) continue;
    if (isScalarField(field)) responses[field.id] = "";
    else metrics[field.id] = "";
  }
  return {
    expected_revision: 1,
    finalize: false,
    responses,
    metrics,
    field_sources: {},
    field_notes: {},
    field_exceptions: {},
  };
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value || {}, key);
}

function sectionAnnotationKey(sectionId) {
  return `section:${sectionId}`;
}

function normalizedSourceContext(value) {
  if (!value || typeof value !== "object") return { source_ids: [], citation: "" };
  return {
    source_ids: Array.isArray(value.source_ids) ? value.source_ids : [],
    citation: String(value.citation || ""),
  };
}

function fieldRequiresSourceLinks(field) {
  return String(field.section_title || "").trim().toLowerCase() !== "basic inputs";
}

function fieldIsReadOnly(field, readonlyIds) {
  const origin = String(field.origin || "").trim().toLowerCase();
  return readonlyIds.has(field.id) || ["derived", "system", "readonly", "read_only", "auto_inherited", "inherited"].includes(origin);
}

function fieldCurrentValue(report, field) {
  const store = isScalarField(field) ? report.responses || {} : report.metrics || {};
  return hasOwn(store, field.id) ? store[field.id] : "";
}

function buildSectionEntryFromField(report, field, readonlyIds) {
  const fieldId = String(field.id || "");
  const note = report.field_notes?.[fieldId] || "";
  const sources = normalizedSourceContext(report.field_sources?.[fieldId]);
  const readOnly = fieldIsReadOnly(field, readonlyIds);
  const entry = {
    field_id: fieldId,
    question: String(field.label || ""),
    description: String(field.help || ""),
    kind: String(field.kind || ""),
    options: Array.isArray(field.options) ? field.options : [],
    max: field.max ?? null,
    origin: String(field.origin || ""),
    path: String(field.path || ""),
    ordinal: Number(field.ordinal || 0),
    read_only: readOnly,
    annotations_allowed: readOnly,
    notes: {
      value: String(note || ""),
      required: Boolean(field.notes_required),
      category: String(field.note_category || ""),
      placeholder: String(field.note_placeholder || ""),
    },
    sources: {
      ...sources,
      required: fieldRequiresSourceLinks(field),
    },
    exception_status: String(report.field_exceptions?.[fieldId] || ""),
  };
  if (readOnly) entry.existing_value = fieldCurrentValue(report, field);
  else entry.value = fieldCurrentValue(report, field);
  return entry;
}

function sectionTemplateFileName(section) {
  return `${String(section.section_ordinal || 0).padStart(2, "0")}-${slugify(section.section_title || section.section_id)}.section.template.json`;
}

function sectionDataQualityValue(section) {
  const quality = section.data_quality || {};
  if (!quality || typeof quality !== "object" || Array.isArray(quality)) return quality || "";
  const keys = Object.keys(quality);
  if (keys.length === 1 && keys[0] === section.section_id) return quality[keys[0]];
  return quality;
}

function buildSectionPatchTemplate(section) {
  return {
    schema_version: Number(section.schema_version || 2),
    report_id: Number(section.report_id || 0),
    stage_key: String(section.stage_key || ""),
    template_id: Number(section.template_id || 0),
    section_id: String(section.section_id || ""),
    section_title: String(section.section_title || ""),
    section_path: String(section.section_path || ""),
    section_ordinal: Number(section.section_ordinal || 0),
    description: String(section.description || ""),
    expected_report_revision: Number(section.report_revision || 1),
    expected_section_revision: Number(section.section_revision || section.report_revision || 1),
    section_rating: section.section_rating ?? "",
    data_quality: sectionDataQualityValue(section),
    section_notes: String(section.section_notes || ""),
    section_sources: normalizedSourceContext(section.section_sources),
    completion: section.completion || {},
    entries: sortedFields(section.entries || []).map((entry) => {
      const readOnly = Boolean(entry.read_only);
      const output = {
        field_id: String(entry.field_id || ""),
        question: String(entry.question || ""),
        description: String(entry.description || ""),
        kind: String(entry.kind || ""),
        options: Array.isArray(entry.options) ? entry.options : [],
        max: entry.max ?? null,
        origin: String(entry.origin || ""),
        path: String(entry.path || ""),
        ordinal: Number(entry.ordinal || 0),
        read_only: readOnly,
        annotations_allowed: Boolean(entry.annotations_allowed),
        notes: {
          value: String(entry.notes?.value || ""),
          required: Boolean(entry.notes?.required),
          category: String(entry.notes?.category || ""),
          placeholder: String(entry.notes?.placeholder || ""),
        },
        sources: {
          ...normalizedSourceContext(entry.sources),
          required: Boolean(entry.sources?.required),
        },
        exception_status: String(entry.exception_status || ""),
      };
      if (readOnly) output.existing_value = entry.value ?? "";
      else output.value = entry.value ?? "";
      return output;
    }),
  };
}

function buildSectionTemplatesFromReport(report) {
  const fullModules = (report.section_modules || []).filter((section) => Array.isArray(section.entries));
  if (fullModules.length) return fullModules.map(buildSectionPatchTemplate);

  const schema = report.template?.schema || {};
  const readonlyIds = new Set(report.agent_contract?.readonly_field_ids || []);
  const summaryById = new Map((report.section_modules || []).map((section) => [String(section.section_id || ""), section]));
  return [...(schema.sections || [])].map((section, index) => {
    const sectionId = String(section.id || "");
    const sectionKey = sectionAnnotationKey(sectionId);
    const summary = summaryById.get(sectionId) || {};
    return buildSectionPatchTemplate({
      schema_version: 2,
      report_id: report.id || 0,
      report_revision: Number(report.revision || 1),
      section_revision: Number(summary.section_revision || report.revision || 1),
      stage_key: report.stage_key || report.template?.stage_key || "",
      template_id: report.template_id || report.template?.id || 0,
      section_id: sectionId,
      section_title: section.title || "",
      section_path: section.path || slugify(section.title || sectionId),
      section_ordinal: Number(section.ordinal || index + 1),
      description: section.body_markdown || "",
      section_rating: report.section_ratings?.[sectionId] ?? "",
      data_quality: hasOwn(report.data_quality || {}, sectionId) ? { [sectionId]: report.data_quality[sectionId] } : {},
      section_notes: report.field_notes?.[sectionKey] || "",
      section_sources: normalizedSourceContext(report.field_sources?.[sectionKey]),
      completion: summary.completion || {},
      entries: sortedFields(section.fields || []).map((field) => buildSectionEntryFromField(report, field, readonlyIds)),
    });
  });
}

function buildSectionTemplatesFromTemplate(template, stage = {}) {
  return buildSectionTemplatesFromReport({
    id: 0,
    revision: 1,
    stage_id: template.stage_id || stage.id || 0,
    stage_key: template.stage_key || stage.key || "",
    stage_name: template.stage_name || stage.name || "",
    template_id: template.id || 0,
    template,
    responses: {},
    metrics: {},
    section_ratings: {},
    data_quality: {},
    field_sources: {},
    field_notes: {},
    field_exceptions: {},
    agent_contract: { readonly_field_ids: [] },
    section_modules: [],
  });
}

function stageFileName(sequence, stageKey) {
  return `${String(sequence).padStart(2, "0")}-${stageKey}.patch.template.json`;
}

function slugify(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "unknown";
}

function timestampToken(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("") + "-" + [pad(date.getHours()), pad(date.getMinutes()), pad(date.getSeconds())].join("");
}

async function writeJson(filePath, payload) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

async function generateAllStages(args) {
  const templatesPayload = args.templatesFile
    ? await readJsonFile(args.templatesFile)
    : readJsonViaCurl(args.apiUrl, "/api/templates");
  const bootstrapPayload = args.bootstrapFile
    ? await readJsonFile(args.bootstrapFile)
    : readJsonViaCurl(args.apiUrl, "/api/bootstrap");

  const stageMap = new Map((bootstrapPayload.stages || []).map((stage) => [Number(stage.id), stage]));
  const outputDir = path.resolve(args.stageDir);
  await fs.mkdir(outputDir, { recursive: true });

  const manifest = {
    generated_from: "active live templates",
    api_url: args.apiUrl,
    templates: [],
  };

  const createReportTemplate = {
    company_id: 0,
    stage_id: 0,
    template_id: 0,
    report_month: "",
    title: "",
  };
  await writeJson(path.join(outputDir, "00-create-report.template.json"), createReportTemplate);

  for (const template of [...(templatesPayload.templates || [])].sort((a, b) => {
    const stageA = stageMap.get(Number(a.stage_id)) || {};
    const stageB = stageMap.get(Number(b.stage_id)) || {};
    return Number(stageA.sequence || 999) - Number(stageB.sequence || 999);
  })) {
    const stage = stageMap.get(Number(template.stage_id)) || {};
    const payload = buildPatchTemplate(template.schema?.fields || []);
    const fileName = stageFileName(stage.sequence || 99, template.stage_key || `stage-${template.stage_id}`);
    await writeJson(path.join(outputDir, fileName), payload);
    const sectionDir = path.join("sections", `${String(stage.sequence || 99).padStart(2, "0")}-${template.stage_key || `stage-${template.stage_id}`}`);
    const sectionFiles = [];
    for (const sectionTemplate of buildSectionTemplatesFromTemplate(template, stage)) {
      const sectionFile = path.join(sectionDir, sectionTemplateFileName(sectionTemplate));
      await writeJson(path.join(outputDir, sectionFile), sectionTemplate);
      sectionFiles.push(sectionFile);
    }
    const generatedFieldCount = Object.keys(payload.responses).length + Object.keys(payload.metrics).length;
    manifest.templates.push({
      stage_id: template.stage_id,
      stage_key: template.stage_key,
      stage_name: template.stage_name,
      template_id: template.id,
      template_name: template.name,
      field_count: template.schema?.field_count || 0,
      generated_patch_key_count: generatedFieldCount,
      generated_section_template_count: sectionFiles.length,
      auto_inherited_field_count: sortedFields(template.schema?.fields || []).filter((field) =>
        String(field.id || "").startsWith("inherited-") ||
        String(field.section_title || "").trim().toLowerCase().startsWith("inherited from ")
      ).length,
      file: fileName,
      section_files: sectionFiles,
    });
  }

  await writeJson(path.join(outputDir, "manifest.json"), manifest);
}

async function generateFromReport(args) {
  let payload;
  if (args.reportFile) {
    payload = await readJsonFile(args.reportFile);
  } else if (args.reportId) {
    payload = readJsonViaCurl(args.apiUrl, `/api/reports/${args.reportId}`);
  } else {
    throw new Error("Provide --report-id or --report-file.");
  }

  const report = payload.report || payload;
  if (!report?.id || !report?.template?.schema?.fields) {
    throw new Error("Input does not look like a report payload.");
  }

  const readonlyIds = new Set(report.agent_contract?.readonly_field_ids || []);
  const template = buildPatchTemplate(report.template.schema.fields || [], readonlyIds);
  template.expected_revision = Number(report.revision || 1);

  if (args.workspaceRoot) {
    const companySlug = slugify(report.company_name || report.ticker || `company-${report.company_id}`);
    const stageSlug = slugify(report.stage_key || report.stage_name || "report");
    const folderName = `${companySlug}__${stageSlug}__${timestampToken()}`;
    const workspaceDir = path.resolve(args.workspaceRoot || DEFAULT_WORKSPACE_ROOT, folderName);
    const livePath = path.join(workspaceDir, "report.live.json");
    const templatePath = path.join(workspaceDir, "report.patch.template.json");
    const patchPath = path.join(workspaceDir, "report.patch.json");
    const sectionTemplates = buildSectionTemplatesFromReport(report);
    const sectionTemplateFiles = sectionTemplates.map((section) => path.join("sections", sectionTemplateFileName(section)));
    const workspaceMeta = {
      workspace_name: folderName,
      created_at: new Date().toISOString(),
      company_id: report.company_id || null,
      company_name: report.company_name || "",
      ticker: report.ticker || "",
      report_id: report.id,
      stage_id: report.stage_id || null,
      stage_key: report.stage_key || "",
      stage_name: report.stage_name || "",
      revision: Number(report.revision || 1),
      files: {
        live_report: "report.live.json",
        patch_template: "report.patch.template.json",
        patch_working_copy: "report.patch.json",
        section_templates: sectionTemplateFiles,
        verify_report: "report.verify.json",
      },
      mcp: {
        endpoint: "/mcp",
        section_resource_template: "funnel://reports/{report_id}/sections/{section_id}",
        preferred_tools: ["list_report_sections", "read_report_section", "preview_report_section", "patch_report_section", "preview_report_completion", "finalize_report"],
      },
    };
    await writeJson(livePath, payload);
    await writeJson(templatePath, template);
    await writeJson(patchPath, template);
    for (const [index, sectionTemplate] of sectionTemplates.entries()) {
      await writeJson(path.join(workspaceDir, sectionTemplateFiles[index]), sectionTemplate);
    }
    await writeJson(path.join(workspaceDir, "workspace.json"), workspaceMeta);
    console.log(workspaceDir);
    return;
  }

  const outPath =
    args.out || path.resolve("/tmp", `report-${report.id}.patch.template.json`);
  await writeJson(outPath, template);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || (!args.allStages && !args.reportId && !args.reportFile)) {
    console.log(usage());
    return;
  }
  if (args.allStages) {
    await generateAllStages(args);
    return;
  }
  await generateFromReport(args);
}

main().catch((error) => {
  console.error(error.message || String(error));
  process.exitCode = 1;
});
