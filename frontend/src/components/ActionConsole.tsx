import { useEffect, useState } from "react";
import NetworkMap, { type NetworkMapNode } from "./NetworkMap";
import { colors, type NodeState } from "../theme/tokens";
import XPToast from "./XPToast";
import {
  useRunSocket,
  VERB_COSTS,
  UNTARGETED_VERBS,
  HOST_TARGETED_VERBS,
  TEXT_TARGETED_VERBS,
  type Verb,
  type HostSummary,
  type RunEndSummary,
  type VerbResult,
} from "../lib/useRunSocket";

/**
 * Phase 2 Item 5 — the action console: 8 verb chips + cost labels, targets
 * picked by tapping the network map (reusing Phase 1's NetworkMap.tsx),
 * mobile-first (this bottom chip bar is the primary input; there is no
 * desktop command-line alternative in this first version — spec calls that
 * "secondary sugar, not the primary path"). Fog of war: before
 * `scan_network`, `run.hosts` is empty and the map is empty — that void IS
 * the fog, not a NetworkMap rendering mode (see PHASE2_STATE.md's note and
 * docs/BACKLOG.md's Phase 5 tone-pass entry on this).
 */

const VERB_LABELS: Record<Verb, string> = {
  scan_network: "Scan Network",
  query_logs: "Query Logs",
  isolate: "Isolate",
  image_disk: "Image Disk",
  interview_user: "Interview User",
  block_ip: "Block IP",
  reset_creds: "Reset Creds",
  escalate: "Escalate",
};

const VERB_ORDER: Verb[] = [
  "scan_network", "query_logs", "isolate", "image_disk",
  "interview_user", "block_ip", "reset_creds", "escalate",
];

const TEXT_TARGET_PROMPT: Record<string, string> = {
  block_ip: "IP address from a revealed log line",
  reset_creds: "Username from a revealed credential",
};

// Client-side layout only — the backend gives topology (edges) but no
// coordinates (NetworkSegment has no x/y, only reachable_from adjacency).
// One column per segment, hosts stacked within it.
function layoutHosts(hosts: HostSummary[]): NetworkMapNode[] {
  const bySegment = new Map<string, HostSummary[]>();
  for (const h of hosts) {
    const list = bySegment.get(h.network_segment_id) ?? [];
    list.push(h);
    bySegment.set(h.network_segment_id, list);
  }
  const segmentIds = [...bySegment.keys()].sort();
  const nodes: NetworkMapNode[] = [];
  segmentIds.forEach((segId, col) => {
    (bySegment.get(segId) ?? []).forEach((h, row) => {
      nodes.push({ id: h.id, label: h.hostname, x: 80 + col * 150, y: 60 + row * 90 });
    });
  });
  return nodes;
}

function hostNodeState(h: HostSummary): NodeState {
  if (h.isolated) return "contained";
  if (h.compromise_level === "none") return "clean";
  if (h.compromise_level === "foothold") return "pulsing";
  return "compromised"; // admin / domain_admin
}

function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface ActionConsoleProps {
  runId: string;
  onComplete?: (summary: RunEndSummary) => void;
}

export default function ActionConsole({ runId, onComplete }: ActionConsoleProps) {
  const run = useRunSocket(runId);
  const [targetVerb, setTargetVerb] = useState<Verb | null>(null);
  const [textInput, setTextInput] = useState("");
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null);
  const [xpVisible, setXpVisible] = useState(false);
  const [resultToast, setResultToast] = useState<VerbResult | null>(null);

  useEffect(() => {
    if (run.runEnd) {
      setXpVisible(run.runEnd.xp_awarded > 0);
      onComplete?.(run.runEnd);
    }
    // Fire once per completed run — run.runEnd only ever transitions null -> summary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.runEnd]);

  useEffect(() => {
    // Surfaces block_ip/reset_creds outcomes — the only verbs that submit
    // without a host tap the drawer can react to on its own. A correct
    // block_ip also earns a host_id (isolation + its IOC), so that host's
    // drawer opens too, same as the host-targeted path below — the point
    // in both cases is that paying for a verb always has an immediate,
    // visible consequence, never a silent state change the player has to
    // go dig for.
    if (!run.lastVerbResult) return;
    setResultToast(run.lastVerbResult);
    if (run.lastVerbResult.hostId) setSelectedHostId(run.lastVerbResult.hostId);
    const timer = setTimeout(() => setResultToast(null), 3500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.lastVerbResult]);

  const nodes = layoutHosts(run.hosts);
  const nodeStates: Record<string, NodeState> = {};
  for (const h of run.hosts) nodeStates[h.id] = hostNodeState(h);

  // Every revealed host is always tappable — either to submit the
  // in-progress host-targeted verb, or (no verb selected) to open its
  // detail drawer. NetworkMap only wires click handlers for ids in this
  // list, so this must stay non-empty outside target-select mode too.
  const clickableNodeIds = run.hosts.map((h) => h.id);

  function handleChipTap(verb: Verb) {
    if (run.runEnd) return;
    if (UNTARGETED_VERBS.includes(verb)) {
      run.submitVerb(verb);
      return;
    }
    setSelectedHostId(null);
    setTextInput("");
    setTargetVerb(verb);
  }

  function handleNodeClick(hostId: string) {
    if (targetVerb) {
      run.submitVerb(targetVerb, hostId);
      setTargetVerb(null);
      // Auto-open this host's drawer — the verb's result (revealed IOCs,
      // forensics, credentials, or just the isolation state) IS the drawer
      // content, and it renders reactively as the delta arrives. Without
      // this, paying 30-90s for a verb had no visible effect until the
      // player happened to tap the same host again.
      setSelectedHostId(hostId);
      return;
    }
    setSelectedHostId(hostId);
  }

  function submitTextTarget() {
    if (!targetVerb || !textInput.trim()) return;
    run.submitVerb(targetVerb, textInput.trim());
    setTargetVerb(null);
    setTextInput("");
  }

  if (run.runEnd) {
    return <RunDebrief summary={run.runEnd} xpVisible={xpVisible} onXpDone={() => setXpVisible(false)} />;
  }

  const selectedHost = run.hosts.find((h) => h.id === selectedHostId) ?? null;
  // Time SPENT, not time remaining — this is a budget the player is
  // drawing down with every verb, not a countdown running on its own; the
  // bar tracks the same number so it visibly moves on every submit instead
  // of only jumping when a stage happens to fire.
  const timeSpent = Math.min(run.attackerClockSeconds, run.capSeconds || run.attackerClockSeconds);
  const clockProgress = run.capSeconds > 0 ? timeSpent / run.capSeconds : 0;
  const capRemaining = Math.max(0, run.capSeconds - run.attackerClockSeconds);
  const nearCap = run.capSeconds > 0 && capRemaining <= 60;

  return (
    <div className="flex flex-col h-full bg-void text-white font-body">
      {/* Clock / stage bar — sticky so it can never scroll out of view once
          the map/drawer/chip bar push the page taller than the viewport. */}
      <div className="sticky top-0 z-20 shrink-0 px-4 pt-3 pb-2 border-b border-dim/20 bg-void">
        <div className="flex items-center justify-between text-xs font-term text-dim mb-1">
          <span>ATTACKER CLOCK</span>
          <span className={nearCap ? "text-bleed" : "text-dim"}>
            {formatClock(timeSpent)} / {formatClock(run.capSeconds)} spent
          </span>
        </div>
        <div className="h-2 rounded-full bg-panel overflow-hidden">
          <div
            className="h-full bg-bleed transition-all duration-500"
            style={{ width: `${Math.min(100, clockProgress * 100)}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-[9px] font-term text-dim/70 mt-1.5">
          <span>STAGES</span>
          <span>{run.stagesFired} / {run.totalStages}</span>
        </div>
      </div>

      {resultToast && (
        <div
          className={`shrink-0 px-4 py-2 text-xs font-term uppercase tracking-widest border-b ${
            resultToast.correct
              ? "text-contain bg-contain/10 border-contain/30"
              : "text-bleed bg-bleed/10 border-bleed/30"
          }`}
        >
          {VERB_LABELS[resultToast.verb]}: {resultToast.correct ? "Correct" : "Incorrect"}
        </div>
      )}

      {run.error && (
        <div className="shrink-0 px-4 py-2 text-xs text-bleed bg-bleed/10 border-b border-bleed/30">
          {run.error}
        </div>
      )}

      {/* Map */}
      <div className="flex-1 min-h-0 overflow-auto relative">
        {nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <div>
              <p className="text-dim font-term text-sm uppercase tracking-widest mb-2">No hosts identified yet</p>
              <p className="text-white/70 text-sm">Tap "Scan Network" below to reveal the topology.</p>
            </div>
          </div>
        ) : (
          <NetworkMap
            nodes={nodes}
            edges={run.edges}
            nodeStates={nodeStates}
            clickableNodeIds={clickableNodeIds}
            onNodeClick={handleNodeClick}
            className="w-full h-full min-h-[280px]"
          />
        )}
      </div>

      {/* Host detail drawer */}
      {selectedHost && !targetVerb && (
        <HostDetailDrawer
          host={selectedHost}
          iocs={run.revealedIocs.filter((i) => i.host_id === selectedHost.id)}
          forensics={run.forensicsByHost[selectedHost.id]}
          credentials={run.credentialsByHost[selectedHost.id]}
          onClose={() => setSelectedHostId(null)}
        />
      )}

      {/* Free-text target input */}
      {targetVerb && TEXT_TARGETED_VERBS.includes(targetVerb) && (
        <div className="shrink-0 border-t border-phosphor/40 bg-panel px-4 py-3">
          <p className="text-xs font-term text-dim uppercase tracking-widest mb-2">
            {VERB_LABELS[targetVerb]} — {TEXT_TARGET_PROMPT[targetVerb]}
          </p>
          <div className="flex gap-2">
            <input
              autoFocus
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitTextTarget()}
              className="flex-1 bg-void border border-dim/40 rounded px-3 py-2 text-sm font-mono text-white outline-none focus:border-phosphor"
              placeholder={targetVerb === "block_ip" ? "203.0.113.4" : "svc_backup"}
            />
            <button
              onClick={submitTextTarget}
              disabled={!textInput.trim()}
              className="px-4 py-2 rounded bg-phosphor text-void font-bold text-sm active:scale-95 disabled:opacity-40"
            >
              Submit
            </button>
            <button
              onClick={() => setTargetVerb(null)}
              className="px-3 py-2 rounded border border-dim/40 text-dim text-sm active:scale-95"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Host-target prompt */}
      {targetVerb && HOST_TARGETED_VERBS.includes(targetVerb) && (
        <div className="shrink-0 border-t border-phosphor/40 bg-panel px-4 py-2 flex items-center justify-between">
          <p className="text-xs font-term text-phosphor uppercase tracking-widest">
            {VERB_LABELS[targetVerb]} — tap a host on the map
          </p>
          <button onClick={() => setTargetVerb(null)} className="text-dim text-xs active:scale-95">Cancel</button>
        </div>
      )}

      {/* Verb chip bar — mobile-first primary input */}
      <div className="shrink-0 grid grid-cols-4 gap-1.5 p-2 bg-panel border-t border-dim/20">
        {VERB_ORDER.map((verb) => (
          <button
            key={verb}
            onClick={() => handleChipTap(verb)}
            disabled={!run.connected}
            className={`flex flex-col items-center justify-center rounded-lg py-2 px-1 min-h-[52px] text-center active:scale-95 transition-colors disabled:opacity-40 ${
              targetVerb === verb ? "bg-phosphor text-void" : "bg-void border border-dim/30 text-white"
            }`}
          >
            <span className="text-[10px] font-bold uppercase tracking-tight leading-tight">{VERB_LABELS[verb]}</span>
            <span className="text-[9px] font-term text-dim mt-0.5">{VERB_COSTS[verb]}s</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function HostDetailDrawer({
  host, iocs, forensics, credentials, onClose,
}: {
  host: HostSummary;
  iocs: { rule_id: string; description: string; source_system: string; severity: string; raw_log: string }[];
  forensics?: { unpatched_cves: string[]; edr_installed: boolean };
  credentials?: { credential_id: string; username: string; privilege: string }[];
  onClose: () => void;
}) {
  const examined = iocs.length > 0 || !!forensics || (credentials && credentials.length > 0);
  return (
    <div className="shrink-0 max-h-[45%] overflow-auto border-t border-dim/30 bg-panel px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <div>
          <p className="font-term text-sm text-white">{host.hostname}</p>
          <p className="text-[10px] text-dim uppercase tracking-widest">{host.role} — {host.compromise_level}{host.isolated ? " — isolated" : ""}</p>
        </div>
        <button onClick={onClose} className="text-dim text-xs active:scale-95">Close</button>
      </div>

      {!examined && (
        <p className="text-sm text-white/60">Not yet examined — try Query Logs, Image Disk, or Interview User on this host.</p>
      )}

      {iocs.map((ioc) => (
        <div key={ioc.rule_id} className="mb-2 border-l-2 border-bleed/50 pl-2">
          <p className="text-xs text-white">{ioc.description}</p>
          <p className="text-[10px] font-mono text-dim">{ioc.source_system} — {ioc.raw_log}</p>
        </div>
      ))}

      {forensics && (
        <div className="mb-2">
          <p className="text-[10px] text-dim uppercase tracking-widest mb-1">Forensics</p>
          <p className="text-xs text-white">EDR installed: {forensics.edr_installed ? "yes" : "no"}</p>
          {forensics.unpatched_cves.length > 0 && (
            <p className="text-xs text-white">Unpatched: {forensics.unpatched_cves.join(", ")}</p>
          )}
        </div>
      )}

      {credentials && credentials.length > 0 && (
        <div>
          <p className="text-[10px] text-dim uppercase tracking-widest mb-1">Credentials seen here</p>
          {credentials.map((c) => (
            <p key={c.credential_id} className="text-xs font-mono text-white">{c.username} ({c.privilege})</p>
          ))}
        </div>
      )}
    </div>
  );
}

function RunDebrief({
  summary, xpVisible, onXpDone,
}: {
  summary: RunEndSummary;
  xpVisible: boolean;
  onXpDone: () => void;
}) {
  const outcomeColor = summary.outcome === "win" ? colors.contain : summary.outcome === "partial" ? colors.phosphor : colors.bleed;
  return (
    <div className="flex flex-col h-full bg-void text-white items-center justify-center px-6 text-center">
      <p className="font-term text-xs uppercase tracking-[0.3em] text-dim mb-2">Run Complete</p>
      <p className="font-display text-3xl font-black mb-4" style={{ color: outcomeColor }}>
        {summary.outcome.toUpperCase()}
      </p>
      <p className="text-4xl font-black mb-1">{summary.score_breakdown.total_score.toLocaleString()}</p>
      <p className="text-dim text-sm mb-6">points — {summary.score_breakdown.score_pct.toFixed(0)}% score</p>

      {summary.rank !== undefined && (
        <div className="mb-6 space-y-1">
          <p className="text-sm text-white">Rank #{summary.rank} today</p>
          {summary.current_streak !== undefined && (
            <p className="text-sm text-dim">🔥 {summary.current_streak}-day streak</p>
          )}
        </div>
      )}

      {xpVisible && (
        <XPToast xp={summary.xp_awarded} achievements={summary.new_achievements} onDone={onXpDone} />
      )}
    </div>
  );
}
