import { isUnknownHost, type HostSummary, type KnownHostSummary } from "./useRunSocket";

/**
 * Client-side incident-feed lines derived from run state the socket
 * already sends. No new backend events.
 *
 * Leak-safety: the only host names this module interpolates come from
 * known-tier `HostSummary`s — the client equivalent of
 * `verb_engine.revealed_host_ids`. Unknown silhouettes (`visibility:
 * "unknown"`, not yet scan_network'd) are skipped, and IOC lines are
 * dropped unless their `host_id` is in that same known set. Stage
 * advances stay a generic "lateral movement" line (the server already
 * redacts stage names/targets from stage.advance).
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

/** Same boundary as the map/API payload: known-tier iff not unknown. */
function isRevealedHost(h: HostSummary): h is KnownHostSummary {
  return !isUnknownHost(h);
}

function revealedHostIds(hosts: HostSummary[]): Set<string> {
  return new Set(hosts.filter(isRevealedHost).map((h) => h.id));
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
  const revealedIds = revealedHostIds(args.hosts);

  if (args.stagesFired > args.prevStagesFired) {
    next.push({
      id: `stage-${args.stagesFired}`,
      ts,
      text: "Lateral movement detected.",
    });
  }

  const prevById = new Map(args.prevHosts.map((h) => [h.id, h]));
  for (const h of args.hosts) {
    if (!isRevealedHost(h)) continue;
    const before = prevById.get(h.id);
    if (h.isolated && (!before || isUnknownHost(before) || !before.isolated)) {
      next.push({
        id: `iso-${h.id}`,
        ts,
        text: `${h.hostname} isolated.`,
      });
    }
    const beforeLevel = before && isRevealedHost(before) ? before.compromise_level : "none";
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
        const rec = ioc as { rule_id?: unknown; description?: unknown; host_id?: unknown };
        if (typeof rec.description !== "string" || !rec.description) continue;
        // Same revealed_host_ids boundary as the map: an IOC whose host
        // is still an unknown silhouette must not become a feed line.
        if (typeof rec.host_id !== "string" || !revealedIds.has(rec.host_id)) continue;
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

