/**
 * Phase 4 — start a ghost race and stash the locked ghost DTO for RaceRoom.
 *
 * POST /action-runs/race returns the ghost DTO once (seed never on ghost).
 * We keep it in sessionStorage keyed by the new run_id so a refresh of
 * /race/:runId can remount GhostPlayback without re-selecting Daily's
 * "run above you" (which could change if the board updates).
 */
import { axiosInstance } from "./api";
import type { GhostDto } from "./ghostPlayback";

const STORAGE_PREFIX = "br_race_ghost:";

export interface RaceStartResponse {
  run_id: string;
  action_run_id: string;
  scenario_id: string;
  seed: number;
  mode: string;
  cap_seconds: number;
  ghost: GhostDto;
}

export type RaceStartBody =
  | { ghost_run_id: string; share_token?: never }
  | { share_token: string; ghost_run_id?: never };

export function stashRaceGhost(runId: string, ghost: GhostDto): void {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${runId}`, JSON.stringify(ghost));
  } catch {
    // Private mode / quota — RaceRoom will show a recoverable error.
  }
}

export function loadRaceGhost(runId: string): GhostDto | null {
  try {
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${runId}`);
    if (!raw) return null;
    return JSON.parse(raw) as GhostDto;
  } catch {
    return null;
  }
}

export function clearRaceGhost(runId: string): void {
  try {
    sessionStorage.removeItem(`${STORAGE_PREFIX}${runId}`);
  } catch {
    /* ignore */
  }
}

export async function startGhostRace(body: RaceStartBody): Promise<RaceStartResponse> {
  const { data } = await axiosInstance.post<RaceStartResponse>("/action-runs/race", body);
  stashRaceGhost(data.run_id, data.ghost);
  return data;
}

/** Safe post-login redirect — same-origin relative path only. */
export function safeAuthNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return null;
  return next;
}
