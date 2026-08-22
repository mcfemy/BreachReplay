import { isUnknownHost, type HostSummary } from "./useRunSocket";

/**
 * Client-side incident-feed lines derived from run state the socket
 * already sends. No new backend events — leak-safe: unknown hosts are
 * never named, and stage advances are a generic "lateral movement" line
 * (the server redacts stage names/targets from stage.advance).
 */

export interface FeedLine {
  id: string;
  ts: string;
  text: string;
}

export function formatFeedClock(elapsedSeconds: number): string {
  const m = Math.floor(elapsedSeconds / 60);
  const s = elapsedSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function appendFeedLines(args: {
  prevStagesFired: number;
  stagesFired: number;
  prevHosts: HostSummary[];
  hosts: HostSummary[];
  lastDeltaChanged: boolean;
  lastDelta: Record<string, unknown> | null;
  elapsedSeconds: number;
}): FeedLine[] {
  const ts = formatFeedClock(args.elapsedSeconds);
  const next: FeedLine[] = [];

  if (args.stagesFired > args.prevStagesFired) {
    next.push({
      id: `stage-${args.stagesFired}`,
      ts,
      text: "Lateral movement detected.",
    });
  }

  const prevById = new Map(args.prevHosts.map((h) => [h.id, h]));
  for (const h of args.hosts) {
    if (isUnknownHost(h)) continue;
    const before = prevById.get(h.id);
    if (h.isolated && (!before || isUnknownHost(before) || !before.isolated)) {
      next.push({
        id: `iso-${h.id}`,
        ts,
        text: `${h.hostname} isolated.`,
      });
    }
    const beforeLevel = before && !isUnknownHost(before) ? before.compromise_level : "none";
    if (h.compromise_level !== "none" && h.compromise_level !== beforeLevel) {
      const fully = h.compromise_level === "admin" || h.compromise_level === "domain_admin";
      next.push({
        id: `comp-${h.id}-${h.compromise_level}`,
        ts,
        text: fully
          ? `${h.hostname} fully compromised.`
          : `${h.hostname} showing signs of compromise.`,
      });
    }
  }

  if (args.lastDeltaChanged && args.lastDelta) {
    const iocs = args.lastDelta.revealed_iocs;
    if (Array.isArray(iocs)) {
      for (const ioc of iocs) {
        if (!ioc || typeof ioc !== "object") continue;
        const rec = ioc as { rule_id?: unknown; description?: unknown };
        if (typeof rec.description !== "string" || !rec.description) continue;
        const iocId = typeof rec.rule_id === "string" ? rec.rule_id : rec.description;
        next.push({ id: `ioc-${iocId}`, ts, text: rec.description });
      }
    }

    const toolOutput = args.lastDelta.tool_output;
    const alreadyCoveredByHost = args.lastDelta.isolated === true;
    if (
      !alreadyCoveredByHost &&
      toolOutput &&
      typeof toolOutput === "object" &&
      typeof (toolOutput as { tool?: unknown }).tool === "string"
    ) {
      const tool = (toolOutput as { tool: string }).tool;
      next.push({
        id: `tool-${tool}-${args.elapsedSeconds}`,
        ts,
        text: tool === "nmap" ? "Network scan complete." : `${tool} activity logged.`,
      });
    }
  }

  return next;
}
