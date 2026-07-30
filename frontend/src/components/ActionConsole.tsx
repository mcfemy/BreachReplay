import { useEffect, useRef, useState } from "react";
import NetworkMap, { type NetworkMapNode } from "./NetworkMap";
import { colors, nodeStateColor, type NodeState } from "../theme/tokens";
import XPToast from "./XPToast";
import ConsolePreBrief from "./ConsolePreBrief";
import { useAuthStore } from "../store/auth";
import { axiosInstance } from "../lib/api";
import {
  useRunSocket,
  VERB_COSTS,
  UNTARGETED_VERBS,
  HOST_TARGETED_VERBS,
  TEXT_TARGETED_VERBS,
  OUTCOME_LABELS,
  type Verb,
  type HostSummary,
  type RunEndSummary,
} from "../lib/useRunSocket";

/**
 * Phase 2 Item 5 — the action console: 8 verb chips + cost labels, targets
 * picked by tapping the network map (reusing Phase 1's NetworkMap.tsx),
 * mobile-first (this bottom chip bar is the primary input; there is no
 * desktop command-line alternative in this first version — spec calls that
 * "secondary sugar, not the primary path"). Fog of war: before
 * `scan_network`, `run.hosts` is empty and the map is empty — that void IS
 * the fog, not a NetworkMap rendering mode (see STATE.md's note and
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

// Guided first-run beats — each fires at most once, only during a player's
// genuine first run (gated by User.has_seen_console_intro, see the
// isGuidedRunRef logic below). Teaches a control, never an answer: no host,
// IP, or direction is ever named, matching the OBJECTIVE line's philosophy.
const GUIDED_BEAT_TEXT = {
  scan: "Red hosts are already compromised. Query one — see how they got in.",
  query: "That log's got the attacker's address in it. Block it.",
  block: "That host's contained. They're still moving through the rest.",
} as const;
type GuidedBeat = keyof typeof GUIDED_BEAT_TEXT;

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
  const user = useAuthStore((s) => s.user);
  const updateUser = useAuthStore((s) => s.updateUser);
  const [targetVerb, setTargetVerb] = useState<Verb | null>(null);
  const [textInput, setTextInput] = useState("");
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null);
  const [xpVisible, setXpVisible] = useState(false);
  const [resultToast, setResultToast] = useState<{ text: string; good: boolean } | null>(null);
  const [toolOutputExpanded, setToolOutputExpanded] = useState(false);
  const [idleNudgeVisible, setIdleNudgeVisible] = useState(false);
  const lastActionAtRef = useRef(0);
  const idleNudgedThisStretchRef = useRef(false);

  // Guided first-run — pre-brief shows only when this account has never
  // seen it. isGuidedRunRef is captured once at mount so the three in-run
  // beats keep firing for the rest of THIS run even after handleDismissPreBrief
  // flips the server-side flag (which would otherwise make a later re-read
  // of `user.has_seen_console_intro` say "no, not guided" mid-run).
  const [showPreBrief, setShowPreBrief] = useState(() => user ? !user.has_seen_console_intro : false);
  const isGuidedRunRef = useRef(showPreBrief);
  const [guidedBeatShown, setGuidedBeatShown] = useState<Record<GuidedBeat, boolean>>({
    scan: false, query: false, block: false,
  });
  const [guidedBeatText, setGuidedBeatText] = useState<string | null>(null);

  function handleDismissPreBrief() {
    setShowPreBrief(false);
    axiosInstance
      .patch("/auth/me", { has_seen_console_intro: true })
      .then(({ data }) => updateUser({ has_seen_console_intro: data.has_seen_console_intro }))
      .catch(() => {
        // Best-effort — worst case the pre-brief shows again next run, not harmful.
      });
  }

  // Run-start baseline for the idle clock — set here (not in the ref
  // initializer above) so Date.now() is never called during render.
  useEffect(() => {
    lastActionAtRef.current = Date.now();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (run.runEnd) {
      setXpVisible(run.runEnd.xp_awarded > 0);
      onComplete?.(run.runEnd);
    }
    // Fire once per completed run — run.runEnd only ever transitions null -> summary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.runEnd]);

  // The core-loop fix: a verb's result must be the immediate visible
  // outcome of paying its cost, not something the player has to already
  // have the right drawer open to notice. Reacts to whatever the server
  // just confirmed (run.lastDelta), not what was optimistically tapped —
  // a rejected verb never produces a state.delta at all, so this never
  // fires on failure. Covers every host-targeted verb uniformly
  // (query_logs/isolate/image_disk/interview_user all carry `host_id`)
  // plus the free-text verbs (block_ip/reset_creds carry `correct`).
  useEffect(() => {
    const delta = run.lastDelta;
    if (!delta) return;

    if (typeof delta.host_id === "string") {
      setSelectedHostId(delta.host_id);
    }

    if (typeof delta.correct === "boolean") {
      setResultToast(
        delta.correct
          ? { text: delta.host_id ? "Correct — host isolated." : "Correct — credential disabled.", good: true }
          : { text: "No match for that input.", good: false },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.lastDelta]);

  useEffect(() => {
    if (!resultToast) return;
    const t = setTimeout(() => setResultToast(null), 3000);
    return () => clearTimeout(t);
  }, [resultToast]);

  // Guided first-run beats — shape-sniffed off the same run.lastDelta every
  // other reaction here uses (see useRunSocket.ts's own shape-sniffing for
  // why: the wire format doesn't tag which verb produced a delta). Each
  // fires at most once, only for isGuidedRunRef.current runs.
  useEffect(() => {
    if (!isGuidedRunRef.current) return;
    const delta = run.lastDelta;
    if (!delta) return;

    if (!guidedBeatShown.scan && Array.isArray(delta.nodes)) {
      setGuidedBeatShown((s) => ({ ...s, scan: true }));
      setGuidedBeatText(GUIDED_BEAT_TEXT.scan);
    } else if (
      !guidedBeatShown.block &&
      delta.correct === true &&
      typeof delta.host_id === "string"
    ) {
      // Correct block_ip — checked before the query branch below since a
      // correct block_ip's delta ALSO carries revealed_iocs (see
      // useRunSocket.ts), which would otherwise false-match as a query beat.
      setGuidedBeatShown((s) => ({ ...s, block: true }));
      setGuidedBeatText(GUIDED_BEAT_TEXT.block);
    } else if (
      !guidedBeatShown.query &&
      Array.isArray(delta.revealed_iocs) &&
      delta.revealed_iocs.length > 0 &&
      !delta.forensics &&
      typeof delta.correct !== "boolean"
    ) {
      // query_logs only — excludes image_disk (carries `forensics`) and
      // block_ip/reset_creds (carry `correct`).
      setGuidedBeatShown((s) => ({ ...s, query: true }));
      setGuidedBeatText(GUIDED_BEAT_TEXT.query);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.lastDelta]);

  useEffect(() => {
    if (!guidedBeatText) return;
    const t = setTimeout(() => setGuidedBeatText(null), 6000);
    return () => clearTimeout(t);
  }, [guidedBeatText]);

  // Idle nudge (onboarding layer 1 — see BREACHREPLAY_GAME_OVERHAUL_SPEC.md
  // Phase 5 for the full guided first-run this is a small slice of). A
  // push to act, never a hint about WHAT to do: no host/IP/direction is
  // named. Any successful verb (a new lastDelta) resets the idle clock and
  // this stretch's one-shot flag, so the nudge can fire again later in the
  // run without ever repeating inside the same idle stretch.
  useEffect(() => {
    if (!run.lastDelta) return;
    lastActionAtRef.current = Date.now();
    idleNudgedThisStretchRef.current = false;
    setIdleNudgeVisible(false);
  }, [run.lastDelta]);

  const IDLE_NUDGE_THRESHOLD_MS = 25_000;

  useEffect(() => {
    if (run.runEnd) return;
    const poll = setInterval(() => {
      if (idleNudgedThisStretchRef.current) return;
      if (guidedBeatText) return; // don't stack the generic nudge on top of a guided beat
      if (Date.now() - lastActionAtRef.current >= IDLE_NUDGE_THRESHOLD_MS) {
        idleNudgedThisStretchRef.current = true;
        setIdleNudgeVisible(true);
      }
    }, 2000);
    return () => clearInterval(poll);
  }, [run.runEnd, guidedBeatText]);

  useEffect(() => {
    if (!idleNudgeVisible) return;
    const t = setTimeout(() => setIdleNudgeVisible(false), 4000);
    return () => clearTimeout(t);
  }, [idleNudgeVisible]);

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

  if (showPreBrief) {
    return <ConsolePreBrief onDismiss={handleDismissPreBrief} />;
  }

  if (run.runEnd) {
    return <RunDebrief summary={run.runEnd} xpVisible={xpVisible} onXpDone={() => setXpVisible(false)} />;
  }

  const selectedHost = run.hosts.find((h) => h.id === selectedHostId) ?? null;
  const capRemaining = Math.max(0, run.capSeconds - run.attackerClockSeconds);
  const stageProgress = run.totalStages > 0 ? run.stagesFired / run.totalStages : 0;

  return (
    <div className="flex flex-col h-full bg-void text-white font-body">
      {/* Clock / stage-progress bar — redacted (no stage names/targets), just length + time */}
      <div className="shrink-0 px-4 pt-3 pb-2 border-b border-dim/20">
        <div className="flex items-center justify-between text-xs font-term text-dim mb-1">
          <span>RESPONSE BUDGET</span>
          <span className={capRemaining <= 60 ? "text-bleed" : "text-dim"}>{formatClock(capRemaining)} left to spend</span>
        </div>
        <div className="h-2 rounded-full bg-panel overflow-hidden">
          <div
            className="h-full bg-bleed transition-all duration-500"
            style={{ width: `${Math.min(100, stageProgress * 100)}%` }}
          />
        </div>
      </div>

      {/* Objective line — persistent, one line, in-voice. Never names a
          host/IP/direction; that deduction is the game (onboarding layer 1,
          see BREACHREPLAY_GAME_OVERHAUL_SPEC.md — the full guided first-run
          is Phase 5, this is deliberately smaller than that). */}
      <div className="shrink-0 px-4 py-1.5 border-b border-dim/20 bg-panel/50">
        <p className="text-[11px] font-term text-white/80 leading-snug">
          <span className="text-phosphor font-bold">OBJECTIVE</span>{" "}
          Contain the breach before the attacker reaches its final target.
        </p>
      </div>

      {run.error && (
        <div className="shrink-0 px-4 py-2 text-xs text-bleed bg-bleed/10 border-b border-bleed/30">
          {run.error}
        </div>
      )}

      {/* Map */}
      <div className="flex-1 min-h-0 overflow-auto relative">
        {/* Legend — colors read directly from nodeStateColor (theme/tokens.ts),
            the same map NetworkMap itself renders from, so this can never
            drift out of sync with what a host's dot actually looks like.
            Teaches the controls, not the deduction: no mention of which
            host/IP is involved, only what a color/connection MEANS. */}
        <div className="absolute top-2 right-2 z-10 bg-panel/90 border border-dim/20 rounded-md px-2 py-1.5 text-[9px] font-term text-dim leading-tight max-w-[150px] pointer-events-none">
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: nodeStateColor.compromised }}
            />
            <span>compromised</span>
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: nodeStateColor.contained }}
            />
            <span>contained</span>
          </div>
          <div className="mt-1 text-dim/70">Attacker spreads along connections.</div>
        </div>

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

      {/* Diegetic tool output — feedback from a security-professional
          tester: the console taught judgment but hid the tooling (tap
          Scan Network, time spent, a map appears, nothing says what ran).
          Shows the real command (where the verb has one) and realistic
          output in that tool's real format, entirely server-rendered
          (backend/app/services/tool_output.py) — never templated here.
          Collapsed by default (one-line summary); a shrink-0 sibling of
          the map, same as the chip bar below, so it never pushes either
          off screen at 390px — only the map's own flex-1 area shrinks to
          make room. */}
      {run.lastDelta?.tool_output && (
        <div className="shrink-0 border-t border-dim/20 bg-panel">
          <button
            onClick={() => setToolOutputExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-1.5 text-left active:opacity-70"
          >
            <span className="text-[10px] font-term uppercase tracking-widest text-phosphor truncate">
              {run.lastDelta.tool_output.tool}
              {run.lastDelta.tool_output.command ? ` — ${run.lastDelta.tool_output.command}` : ""}
            </span>
            <span className="text-dim text-xs shrink-0 ml-2">{toolOutputExpanded ? "▲" : "▼"}</span>
          </button>
          {toolOutputExpanded && (
            <pre className="max-h-32 overflow-y-auto px-4 pb-2 text-[10px] font-mono text-white/80 whitespace-pre-wrap break-words">
              {run.lastDelta.tool_output.output}
            </pre>
          )}
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

      {/* block_ip / reset_creds result — these have no host-drawer to open
          on a wrong guess (and reset_creds never opens one at all), so this
          is their only visible confirmation that the cost bought something. */}
      {resultToast && (
        <div
          className={`fixed bottom-24 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-full text-sm font-bold shadow-lg ${
            resultToast.good ? "bg-contain text-void" : "bg-bleed text-void"
          }`}
        >
          {resultToast.good ? "✓ " : "✗ "}{resultToast.text}
        </div>
      )}

      {/* Idle nudge — a push to act, never a hint about what to do: names
          no host, IP, or direction. Onboarding layer 1 (see the objective
          line's comment above); fires at most once per idle stretch. */}
      {idleNudgeVisible && (
        <div className="fixed bottom-40 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-full text-sm font-bold shadow-lg bg-phosphor text-void">
          The attacker is still active — every second counts.
        </div>
      )}

      {/* Guided first-run beats — same toast system as the idle nudge above,
          each fires at most once, only during a player's genuine first run. */}
      {guidedBeatText && (
        <div className="fixed bottom-40 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-full text-sm font-bold shadow-lg bg-phosphor text-void max-w-[90vw] text-center">
          {guidedBeatText}
        </div>
      )}
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

// Proportionate Response debrief color per named outcome (label text comes
// from useRunSocket's shared OUTCOME_LABELS). Only 3 semantic colors exist
// in theme/tokens.ts (contain/phosphor/bleed), so `overreacted`
// deliberately reads as `bleed` (red) rather than amber: it technically
// stopped the final target but earns zero XP and no achievements (see
// action_run_store.finalize's gating comment) — the debrief should read as
// a failure of proportionality, not a near-miss.
const OUTCOME_COLOR: Record<RunEndSummary["outcome"], string> = {
  contained: colors.contain,
  contained_at_cost: colors.phosphor,
  overreacted: colors.bleed,
  breached_spread_limited: colors.phosphor,
  breached: colors.bleed,
};

function RunDebrief({
  summary, xpVisible, onXpDone,
}: {
  summary: RunEndSummary;
  xpVisible: boolean;
  onXpDone: () => void;
}) {
  const outcomeLabel = OUTCOME_LABELS[summary.outcome].toUpperCase();
  const outcomeColor = OUTCOME_COLOR[summary.outcome];
  const collateral = summary.score_breakdown.collateral ?? [];
  return (
    <div className="flex flex-col h-full bg-void text-white items-center justify-center px-6 text-center">
      <p className="font-term text-xs uppercase tracking-[0.3em] text-dim mb-2">Run Complete</p>
      <p className="font-display text-3xl font-black mb-4" style={{ color: outcomeColor }}>
        {outcomeLabel}
      </p>
      <p className="text-4xl font-black mb-1">{summary.score_breakdown.total_score.toLocaleString()}</p>
      <p className="text-dim text-sm mb-6">points — {summary.score_breakdown.score_pct.toFixed(0)}% score</p>

      {/* Collateral line — named, not a buried percentage: the specific
          systems taken offline unnecessarily, per spec section 5. Silent
          (renders nothing) on a clean run rather than announcing "0
          unnecessary systems", matching how the rank block below only
          renders when there's something to say. */}
      {collateral.length > 0 && (
        <div className="mb-6 max-w-sm">
          <p className="font-term text-xs uppercase tracking-[0.2em] text-dim mb-1">
            Taken Offline Unnecessarily
          </p>
          <p className="text-sm text-white">
            {collateral.map((h) => h.hostname).join(", ")}
          </p>
        </div>
      )}

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
