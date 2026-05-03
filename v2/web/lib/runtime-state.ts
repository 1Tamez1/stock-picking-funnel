import { promises as fs } from "fs";
import path from "path";

export interface WriteFreezeState {
  writeFrozen: boolean;
  reason: string;
  message: string;
  source: string;
  createdAt: string;
}

export interface CutoverState {
  phase: string;
  status: string;
  rollbackAuthority: string;
  cutbackRequired: boolean;
  reason: string;
  message: string;
  source: string;
  createdAt: string;
  manifestPath: string;
}

function markerPath(): string {
  return process.env.FUNNEL_V2_WRITE_FREEZE_MARKER || path.resolve(process.cwd(), "../contracts/hosted-runtime/write-freeze.json");
}

function cutoverMarkerPath(): string {
  return process.env.FUNNEL_V2_CUTOVER_STATE_PATH || path.resolve(process.cwd(), "../contracts/hosted-runtime/cutover-state.json");
}

export async function readWriteFreezeState(): Promise<WriteFreezeState> {
  const defaultState: WriteFreezeState = {
    writeFrozen: false,
    reason: "",
    message: "",
    source: "",
    createdAt: "",
  };
  try {
    const raw = await fs.readFile(markerPath(), "utf-8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      ...defaultState,
      writeFrozen: Boolean(parsed.write_frozen ?? true),
      reason: String(parsed.reason || ""),
      message: String(parsed.message || ""),
      source: String(parsed.source || ""),
      createdAt: String(parsed.created_at || ""),
    };
  } catch {
    return defaultState;
  }
}

export async function readCutoverState(): Promise<CutoverState> {
  const defaultState: CutoverState = {
    phase: "idle",
    status: "idle",
    rollbackAuthority: "sqlite",
    cutbackRequired: false,
    reason: "",
    message: "",
    source: "",
    createdAt: "",
    manifestPath: "",
  };
  try {
    const raw = await fs.readFile(cutoverMarkerPath(), "utf-8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      ...defaultState,
      phase: String(parsed.phase || "idle"),
      status: String(parsed.status || "idle"),
      rollbackAuthority: String(parsed.rollback_authority || "sqlite"),
      cutbackRequired: Boolean(parsed.cutback_required || false),
      reason: String(parsed.reason || ""),
      message: String(parsed.message || ""),
      source: String(parsed.source || ""),
      createdAt: String(parsed.created_at || ""),
      manifestPath: String(parsed.manifest_path || ""),
    };
  } catch {
    return defaultState;
  }
}
