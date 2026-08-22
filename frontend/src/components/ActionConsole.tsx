import { useEffect, useRef, useState } from "react";
import NetworkMap, { type NetworkMapNode } from "./NetworkMap";
import { colors, nodeStateColor, NODE_STATE_LEGEND, type NodeState } from "../theme/tokens";
import XPToast from "./XPToast";
import ConsolePreBrief from "./ConsolePreBrief";
import Coachmark from "./Coachmark";
import { useAuthStore } from "../store/auth";
import { axiosInstance } from "../lib/api";
import {
  useRunSocket,
  VERB_COSTS,
  UNTARGETED_VERBS,
  HOST_TARGETED_VERBS,
  TEXT_TARGETED_VERBS,
  PARTY_TARGETED_VERBS,
  OUTCOME_LABELS,
  type Verb,
  type HostSummary,
  type KnownHostSummary,
  type RunEndSummary,
  isUnknownHost,
} from "../lib/useRunSocket";
import { playChime, playTick, playThud } from "../lib/sound";
import { appendFeedLines, type FeedLine } from "../lib/runFeed";
import AlertFeed from "./AlertFeed";

/**
 * Phase 2 Item 5 — the action console: 8 verb chips + cost labels, targets
 * picked by tapping the network map (reusing Phase 1's NetworkMap.tsx),
 * mobile-first (this bottom chip bar is the primary input; there is no
 * desktop command-line alternative in this first version — spec calls that
 * "secondary sugar, not the primary path"). Fog of war is two tiers:
 * unknown silhouettes (id + position, no identity/compromise) until
 * `scan_network`, then known hosts with full `_host_summary` fields.
 * `scan_network` itself is unchanged — it still returns every host's
 * full node list in one shot.
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

// Per-verb coachmarks — what each of the 8 verbs actually does, shown once
// ever per account (User.seen_verb_coachmarks) the first time that specific
// verb is tapped, anchored to its own chip. Explains the control, never the
// answer: no host, IP, or direction is ever named, matching the OBJECTIVE
// line's philosophy. Replaces the old GUIDED_BEAT_TEXT system, which only
// ever covered 3 of the 8 verbs and only during a player's first-ever run.
const VERB_COACHMARK_TEXT: Record<Verb, string> = {
  scan_network: "Reveals the network topology — every host on the map, and which ones are already compromised.",
  query_logs: "Pulls log data from a host. May reveal indicators of compromise.",
  isolate: "Cuts a host off the network, containing anything active on it.",
  image_disk: "Takes a forensic disk image. Reveals unpatched vulnerabilities and EDR status.",
  interview_user: "Interviews the host's user. May reveal credentials seen in use.",
  block_ip: "Blocks an IP address at the firewall.",
  reset_creds: "Forces a credential reset, disabling it for the attacker.",
  escalate: "Notifies a party outside the console. Over-notifying has a cost too — use judgment.",
};

// Derives from the same targeting-group arrays the rest of this file uses
// (HOST_TARGETED_VERBS etc, imported from useRunSocket) rather than a
// separate hardcoded map, so it can never drift out of sync with them.
function targetingHintFor(verb: Verb): string {
  if (UNTARGETED_VERBS.includes(verb)) return "No target — fires immediately.";
  if (HOST_TARGETED_VERBS.includes(verb)) return "Tap a host on the map to target it.";
  if (TEXT_TARGETED_VERBS.includes(verb)) return `Type the ${TEXT_TARGET_PROMPT[verb]}.`;
  return "Pick who to notify from the list.";
}

// Client-side layout only — the backend gives topology (edges) but
// scan_network's live delta still has no coordinates (NetworkSegment has
// no x/y, only reachable_from adjacency). Unknown-tier hosts arrive with
// server-computed x/y from the same formula; if every host has coords we
// use those so silhouettes sit on the same grid a later scan will occupy.
// One column per segment, hosts stacked within it. Numbers must match
// verb_engine._host_map_positions (_MAP_ORIGIN_X/Y, _MAP_COL/ROW_GAP).
function hasMapPosition(h: HostSummary): h is HostSummary & { x: number; y: number } {
  return typeof (h as { x?: unknown }).x === "number" && typeof (h as { y?: unknown }).y === "number";
}

function layoutHosts(hosts: HostSummary[]): NetworkMapNode[] {
  if (hosts.length > 0 && hosts.every(hasMapPosition)) {
    return hosts.map((h) => ({
      id: h.id,
      label: isUnknownHost(h) ? "" : h.hostname,
      x: h.x,
      y: h.y,
    }));
  }
  const bySegment = new Map<string, KnownHostSummary[]>();
  for (const h of hosts) {
    if (isUnknownHost(h)) continue;
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
  if (isUnknownHost(h)) return "unknown";
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
  // nmap specifically streams line-by-line instead of appearing all at
  // once — "as though it's a real exercise" — everything else stays a
  // static reveal on expand. Purely a client-side rendering pace over
  // already-deterministic server content (tool_output.py's own output
  // string never changes); it has no bearing on scoring, action_log, or
  // Phase 4 ghost-replay determinism, which only ever depend on that
  // string's CONTENT, never how long the client took to animate it.
  const [nmapRevealedLines, setNmapRevealedLines] = useState<string[]>([]);
  const nmapStreamRef = useRef<{ lines: string[]; timer: ReturnType<typeof setInterval> | null }>({ lines: [], timer: null });
  const toolOutputScrollRef = useRef<HTMLPreElement | null>(null);
  const [idleNudgeVisible, setIdleNudgeVisible] = useState(false);
  const lastActionAtRef = useRef(0);
  const idleNudgedThisStretchRef = useRef(false);
  const [feedLines, setFeedLines] = useState<FeedLine[]>([]);
  const feedPrimedRef = useRef(false);
  const prevStagesFiredRef = useRef(0);
  const prevHostsRef = useRef<HostSummary[]>([]);
  const prevLastDeltaRef = useRef<unknown>(null);
  const elapsedForFeedRef = useRef(0);
  elapsedForFeedRef.current = run.elapsedSeconds;

  // Guided first-run pre-brief — shows only when this account has never seen it.
  const [showPreBrief, setShowPreBrief] = useState(() => user ? !user.has_seen_console_intro : false);

  // Per-verb coachmarks — coachmarkVerb is the one currently showing (at
  // most one at a time, first-use-intercepted by handleChipTap below).
  // seenCoachmarks starts from the account's persisted set and is updated
  // optimistically on dismiss (see handleDismissCoachmark) so a rapid
  // second tap of the same verb, before the PATCH round-trip resolves,
  // never re-shows a coachmark the player just dismissed.
  const [coachmarkVerb, setCoachmarkVerb] = useState<Verb | null>(null);
  const [seenCoachmarks, setSeenCoachmarks] = useState<Set<Verb>>(
    () => new Set((user?.seen_verb_coachmarks ?? []) as Verb[]),
  );
  const chipRefs = useRef<Partial<Record<Verb, HTMLButtonElement | null>>>({});
  const pressureTickFired = useRef(false);

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
      if (run.runEnd.outcome === "contained" || run.runEnd.outcome === "contained_at_cost") {
        playChime();
      }
    }
    // Fire once per completed run — run.runEnd only ever transitions null -> summary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.runEnd]);

  useEffect(() => {
    if (run.capSeconds <= 0 || pressureTickFired.current) return;
    const remaining = Math.max(0, run.capSeconds - run.attackerClockSeconds);
    if (remaining <= 60) {
      pressureTickFired.current = true;
      playTick();
    }
  }, [run.capSeconds, run.attackerClockSeconds]);

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

    // query_logs and image_disk both carry `revealed_iocs` with no
    // `correct` flag — their diegetic tool panel (Splunk / dd+sha256sum)
    // already shows that same IOC content, so auto-opening the drawer too
    // just duplicates it on a 390px screen. block_ip's correct guess also
    // carries revealed_iocs, but its tool panel (iptables) shows a
    // DIFFERENT thing (the rule pushed, not the IOC) — `correct` being a
    // boolean is what distinguishes it, so it keeps opening the drawer.
    const toolPanelAlreadyShowsThisReveal =
      Array.isArray(delta.revealed_iocs) && typeof delta.correct !== "boolean";

    if (typeof delta.host_id === "string" && !toolPanelAlreadyShowsThisReveal) {
      setSelectedHostId(delta.host_id);
    }

    if (typeof delta.correct === "boolean") {
      setResultToast(
        delta.correct
          ? { text: delta.host_id ? "Correct — host isolated." : "Correct — credential disabled.", good: true }
          : { text: "No match for that input.", good: false },
      );
    }

    // escalate (Phase 3) — same immediate-feedback pattern block_ip/
    // reset_creds already get above: the player learns right away whether
    // this specific notification was warranted, not only in the final
    // debrief. Not a world-state leak (it's feedback on the player's OWN
    // action, same category as block_ip's "Correct"/"No match"), unlike
    // IOC content or attacker-stage state.
    if (typeof delta.warranted === "boolean" && typeof delta.party_name === "string") {
      setResultToast(
        delta.warranted
          ? { text: `Notified ${delta.party_name} — warranted.`, good: true }
          : { text: `Notified ${delta.party_name} — not warranted.`, good: false },
      );
    }

    if (delta.isolated === true || delta.correct === true) {
      playThud();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.lastDelta]);

  useEffect(() => {
    if (!resultToast) return;
    const t = setTimeout(() => setResultToast(null), 3000);
    return () => clearTimeout(t);
  }, [resultToast]);

  // nmap's tool output streams in line by line, like watching the scan
  // actually run, instead of the static instant reveal every other verb
  // gets — forces the panel open for this one case only. Every OTHER
  // verb's result resets the panel back to collapsed (not just "leaves it
  // however it was") — otherwise, once nmap opened it once, it would stay
  // pinned open for every later verb too, silently breaking the "collapsed
  // by default" call for everything that isn't nmap.
  useEffect(() => {
    const toolOutput = run.lastDelta?.tool_output;
    if (!toolOutput) return;

    if (toolOutput.tool !== "nmap") {
      if (nmapStreamRef.current.timer) {
        clearInterval(nmapStreamRef.current.timer);
        nmapStreamRef.current.timer = null;
      }
      setToolOutputExpanded(false);
      return;
    }

    if (nmapStreamRef.current.timer) clearInterval(nmapStreamRef.current.timer);
    const lines = toolOutput.output.split("\n");
    nmapStreamRef.current.lines = lines;
    setNmapRevealedLines([]);
    setToolOutputExpanded(true);

    let i = 0;
    nmapStreamRef.current.timer = setInterval(() => {
      i += 1;
      setNmapRevealedLines(lines.slice(0, i));
      if (toolOutputScrollRef.current) {
        toolOutputScrollRef.current.scrollTop = toolOutputScrollRef.current.scrollHeight;
      }
      if (i >= lines.length && nmapStreamRef.current.timer) {
        clearInterval(nmapStreamRef.current.timer);
        nmapStreamRef.current.timer = null;
      }
    }, 45);

    return () => {
      if (nmapStreamRef.current.timer) clearInterval(nmapStreamRef.current.timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.lastDelta]);

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

  // Incident feed — client-side rendering of events the socket already
  // delivered (stage.advance, host isolate/compromise, lastDelta IOCs).
  // Primed on first snapshot so a reconnect/resync doesn't dump history
  // as if it just happened.
  useEffect(() => {
    if (!feedPrimedRef.current) {
      feedPrimedRef.current = true;
      prevStagesFiredRef.current = run.stagesFired;
      prevHostsRef.current = run.hosts;
      prevLastDeltaRef.current = run.lastDelta;
      return;
    }
    const added = appendFeedLines({
      prevStagesFired: prevStagesFiredRef.current,
      stagesFired: run.stagesFired,
      prevHosts: prevHostsRef.current,
      hosts: run.hosts,
      lastDeltaChanged: run.lastDelta !== prevLastDeltaRef.current,
      lastDelta: run.lastDelta,
      elapsedSeconds: elapsedForFeedRef.current,
    });
    prevStagesFiredRef.current = run.stagesFired;
    prevHostsRef.current = run.hosts;
    prevLastDeltaRef.current = run.lastDelta;
    if (added.length) setFeedLines((prev) => [...prev, ...added].slice(-40));
  }, [run.stagesFired, run.hosts, run.lastDelta]);

  const IDLE_NUDGE_THRESHOLD_MS = 25_000;

  useEffect(() => {
    if (run.runEnd) return;
    const poll = setInterval(() => {
      if (idleNudgedThisStretchRef.current) return;
      if (coachmarkVerb) return; // don't stack the generic nudge on top of an active coachmark
      if (Date.now() - lastActionAtRef.current >= IDLE_NUDGE_THRESHOLD_MS) {
        idleNudgedThisStretchRef.current = true;
        setIdleNudgeVisible(true);
      }
    }, 2000);
    return () => clearInterval(poll);
  }, [run.runEnd, coachmarkVerb]);

  useEffect(() => {
    if (!idleNudgeVisible) return;
    const t = setTimeout(() => setIdleNudgeVisible(false), 4000);
    return () => clearTimeout(t);
  }, [idleNudgeVisible]);

  const nodes = layoutHosts(run.hosts);
  const nodeStates: Record<string, NodeState> = {};
  for (const h of run.hosts) nodeStates[h.id] = hostNodeState(h);

  // Known hosts are tappable — either to submit the in-progress
  // host-targeted verb, or (no verb selected) to open the detail drawer.
  // Unknown silhouettes are visible but not targets: tapping one before
  // scan would let isolate's `on_attack_path` (and the drawer) leak
  // known-tier status. NetworkMap only wires click handlers for ids in
  // this list.
  const clickableNodeIds = run.hosts.filter((h) => !isUnknownHost(h)).map((h) => h.id);

  // First tap of a verb this account has never seen a coachmark for is
  // intercepted here — the coachmark explains the control before anything
  // is submitted or a target-select UI opens; performVerbTap (the original
  // tap logic) only runs once it's dismissed. Every later tap of that same
  // verb skips straight to performVerbTap.
  function handleChipTap(verb: Verb) {
    if (run.runEnd) return;
    if (!seenCoachmarks.has(verb)) {
      setCoachmarkVerb(verb);
      return;
    }
    performVerbTap(verb);
  }

  function performVerbTap(verb: Verb) {
    if (UNTARGETED_VERBS.includes(verb)) {
      run.submitVerb(verb);
      return;
    }
    // Fallback for a scenario with no authored notification matrix yet
    // (found in review on PR #25) — verb_engine's own apply_verb falls
    // back to escalate's pre-Phase-3 untargeted behavior in this exact
    // case, so the UI must match it: submit immediately instead of
    // opening a party picker with nothing in it.
    if (PARTY_TARGETED_VERBS.includes(verb) && run.notificationParties.length === 0) {
      run.submitVerb(verb);
      return;
    }
    setSelectedHostId(null);
    setTextInput("");
    setTargetVerb(verb);
  }

  // Same best-effort PATCH pattern as handleDismissPreBrief above: update
  // local state immediately, persist in the background, swallow failure
  // (worst case this verb's coachmark shows once more next time).
  function handleDismissCoachmark() {
    if (!coachmarkVerb) return;
    const verb = coachmarkVerb;
    const nextSeen = Array.from(new Set([...seenCoachmarks, verb]));
    setCoachmarkVerb(null);
    setSeenCoachmarks(new Set(nextSeen));
    axiosInstance
      .patch("/auth/me", { seen_verb_coachmarks: nextSeen })
      .then(({ data }) => updateUser({ seen_verb_coachmarks: data.seen_verb_coachmarks }))
      .catch(() => {
        // Best-effort — worst case the coachmark shows again next tap, not harmful.
      });
    performVerbTap(verb);
  }

  function handleNodeClick(hostId: string) {
    // Guarded to HOST_TARGETED_VERBS specifically (Phase 3) — the map
    // stays visible and tappable while a text-target or party-target
    // prompt is up (they render as siblings below it, not an overlay), so
    // an unguarded `if (targetVerb)` here would let a stray map tap
    // submit escalate (or block_ip/reset_creds) with a host id instead of
    // its real target.
    if (targetVerb && HOST_TARGETED_VERBS.includes(targetVerb)) {
      run.submitVerb(targetVerb, hostId);
      setTargetVerb(null);
      return;
    }
    if (targetVerb) return;
    setSelectedHostId(hostId);
  }

  function submitPartyTarget(partyId: string) {
    if (!targetVerb) return;
    run.submitVerb(targetVerb, partyId);
    setTargetVerb(null);
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
  const selectedKnownHost = selectedHost && !isUnknownHost(selectedHost) ? selectedHost : null;
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

      <AlertFeed lines={feedLines} />

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
            NODE_STATE_LEGEND is every NodeState; adding a state without
            putting it here is a type error. Teaches the controls, not the
            deduction: no mention of which host/IP is involved. */}
        <div className="absolute top-2 right-2 z-10 bg-panel/90 border border-dim/20 rounded-md px-2 py-1.5 text-[9px] font-term text-dim leading-tight max-w-[150px] pointer-events-none">
          {NODE_STATE_LEGEND.map((state, i) => (
            <div key={state} className={`flex items-center gap-1.5${i === 0 ? "" : " mt-1"}`}>
              <span
                className="inline-block w-2 h-2 rounded-full shrink-0"
                style={{
                  backgroundColor: state === "unknown" ? "transparent" : nodeStateColor[state],
                  border: `1.5px ${state === "unknown" ? "dashed" : "solid"} ${nodeStateColor[state]}`,
                }}
              />
              <span>{state}</span>
            </div>
          ))}
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
      {selectedKnownHost && !targetVerb && (
        <HostDetailDrawer
          host={selectedKnownHost}
          iocs={run.revealedIocs.filter((i) => i.host_id === selectedKnownHost.id)}
          forensics={run.forensicsByHost[selectedKnownHost.id]}
          credentials={run.credentialsByHost[selectedKnownHost.id]}
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

      {/* Party-target picker (Phase 3 — escalate) — only ever reachable
          when run.notificationParties is non-empty (handleChipTap submits
          immediately, matching verb_engine's own matrix-less fallback,
          otherwise — see that function's comment). Deliberately shows
          only {id, party_name} (run.notificationParties, redacted
          server-side, see verb_engine.public_notification_parties): never
          `warranted`, or the picker would hand the player the judgment
          call this verb exists to test. Already-notified parties
          (run.notifiedPartyIds) are shown disabled rather than hidden —
          confirms to the player what they've already done instead of
          silently shrinking the list. */}
      {targetVerb && PARTY_TARGETED_VERBS.includes(targetVerb) && (
        <div className="shrink-0 border-t border-phosphor/40 bg-panel px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-term text-phosphor uppercase tracking-widest">
              {VERB_LABELS[targetVerb]} — who do you notify?
            </p>
            <button onClick={() => setTargetVerb(null)} className="text-dim text-xs active:scale-95">Cancel</button>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {run.notificationParties.map((party) => {
              const alreadyNotified = run.notifiedPartyIds.includes(party.id);
              return (
                <button
                  key={party.id}
                  onClick={() => submitPartyTarget(party.id)}
                  disabled={alreadyNotified}
                  className="px-3 py-2 rounded bg-void border border-dim/30 text-white text-xs font-bold text-left active:scale-95 disabled:opacity-40"
                >
                  <span>{party.party_name}</span>
                  {alreadyNotified && <span className="block text-[9px] font-normal text-dim mt-0.5">Already notified</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Diegetic tool output — feedback from a security-professional
          tester: the console taught judgment but hid the tooling (tap
          Scan Network, time spent, a map appears, nothing says what ran).
          Shows the real command (where the verb has one) and realistic
          output in that tool's real format, entirely server-rendered
          (backend/app/services/tool_output.py) — never templated here.
          Collapsed by default (tool name only — the command lives in the
          expanded body, not the header, so a long Splunk query never
          truncates mid-word); a shrink-0 sibling of the map, same as the
          chip bar below, so it never pushes either off screen at 390px —
          only the map's own flex-1 area shrinks to make room. */}
      {run.lastDelta?.tool_output && (
        <div className="shrink-0 border-t border-dim/20 bg-panel">
          <button
            onClick={() => setToolOutputExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-1.5 text-left active:opacity-70"
          >
            <span className="text-[10px] font-term uppercase tracking-widest text-phosphor truncate">
              {run.lastDelta.tool_output.tool}
            </span>
            <span className="text-dim text-xs shrink-0 ml-2">{toolOutputExpanded ? "▲" : "▼"}</span>
          </button>
          {toolOutputExpanded && (
            <div className="px-4 pb-2">
              {run.lastDelta.tool_output.command && (
                <p className="text-[10px] font-mono text-phosphor/80 mb-1 break-all">
                  $ {run.lastDelta.tool_output.command}
                </p>
              )}
              <pre
                ref={toolOutputScrollRef}
                className="max-h-32 overflow-y-auto text-[10px] font-mono text-white/80 whitespace-pre-wrap break-words"
              >
                {run.lastDelta.tool_output.tool === "nmap"
                  ? nmapRevealedLines.join("\n")
                  : run.lastDelta.tool_output.output}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Verb chip bar — mobile-first primary input */}
      <div className="shrink-0 grid grid-cols-4 gap-1.5 p-2 bg-panel border-t border-dim/20">
        {VERB_ORDER.map((verb) => (
          <button
            key={verb}
            ref={(el) => { chipRefs.current[verb] = el; }}
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

      {/* Per-verb coachmark — anchored to the tapped chip, shown at most
          once ever per verb per account (User.seen_verb_coachmarks). */}
      {coachmarkVerb && (
        <Coachmark
          anchorEl={chipRefs.current[coachmarkVerb] ?? null}
          text={VERB_COACHMARK_TEXT[coachmarkVerb]}
          targetingHint={targetingHintFor(coachmarkVerb)}
          onDismiss={handleDismissCoachmark}
        />
      )}
    </div>
  );
}

function HostDetailDrawer({
  host, iocs, forensics, credentials, onClose,
}: {
  host: KnownHostSummary;
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

function RunDebriefShare({ actionRunId }: { actionRunId: string }) {
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareCard, setShareCard] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function mint() {
    setSharing(true);
    setError(null);
    try {
      const { data } = await axiosInstance.post<{
        share_token: string;
        share_url_path: string;
        share_card: string;
      }>(`/action-runs/${actionRunId}/share`);
      setShareUrl(window.location.origin + data.share_url_path);
      setShareCard(data.share_card);
      setCopied(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not create share link");
    } finally {
      setSharing(false);
    }
  }

  function copy() {
    const text = shareCard ?? shareUrl;
    if (!text) return;
    void navigator.clipboard?.writeText(text);
    setCopied(true);
  }

  return (
    <div className="mb-6 max-w-sm w-full">
      {!shareUrl ? (
        <button
          type="button"
          onClick={() => void mint()}
          disabled={sharing}
          className="font-term text-xs uppercase tracking-[0.2em] text-phosphor border border-phosphor/40 px-3 py-2 rounded disabled:opacity-50"
        >
          {sharing ? "Creating link…" : "Share this run"}
        </button>
      ) : (
        <button
          type="button"
          onClick={copy}
          className="font-term text-xs uppercase tracking-[0.2em] text-contain border border-contain/40 px-3 py-2 rounded w-full"
        >
          {copied ? "Copied" : "Copy share card"}
        </button>
      )}
      {shareUrl && (
        <p className="mt-2 text-[10px] text-dim break-all">{shareUrl}</p>
      )}
      {error && <p className="mt-2 text-[10px] text-bleed">{error}</p>}
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
  const outcomeLabel = OUTCOME_LABELS[summary.outcome].toUpperCase();
  const outcomeColor = OUTCOME_COLOR[summary.outcome];
  const collateral = summary.score_breakdown.collateral ?? [];
  // Phase 3 — two lines, same "show the mistake, not just the score"
  // spirit as the collateral line above: who was actually notified
  // (tagged warranted/not), and separately, which warranted party the
  // run never notified at all. Both silent when empty, matching how the
  // collateral line above renders nothing on a clean run.
  const notifications = summary.score_breakdown.notifications ?? [];
  const notified = notifications.filter((n) => n.notified);
  const missedWarranted = notifications.filter((n) => n.warranted && !n.notified);
  return (
    <div className="flex flex-col h-full bg-void text-white items-center justify-center px-6 text-center">
      <p className="font-term text-xs uppercase tracking-[0.3em] text-dim mb-2">Run Complete</p>
      <p className="font-display text-3xl font-black mb-4" style={{ color: outcomeColor }}>
        {outcomeLabel}
      </p>
      <p className="text-4xl font-black mb-1">{summary.score_breakdown.total_score.toLocaleString()}</p>
      <p className="text-dim text-sm mb-6">points — {summary.score_breakdown.score_pct.toFixed(0)}% score</p>

      <RunDebriefShare actionRunId={summary.action_run_id} />

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

      {/* Phase 3 — notification proportionality, same "name the specific
          mistake" treatment as collateral above. Warranted notifications
          read green (contain), unwarranted ones read the same bleed red
          as overreacted collateral does — over-notifying is a real cost,
          not a near-miss. */}
      {notified.length > 0 && (
        <div className="mb-6 max-w-sm">
          <p className="font-term text-xs uppercase tracking-[0.2em] text-dim mb-1">Notifications Made</p>
          <p className="text-sm">
            {notified.map((n, i) => (
              <span key={n.party_id}>
                {i > 0 && ", "}
                <span style={{ color: n.warranted ? colors.contain : colors.bleed }}>{n.party_name}</span>
              </span>
            ))}
          </p>
        </div>
      )}
      {missedWarranted.length > 0 && (
        <div className="mb-6 max-w-sm">
          <p className="font-term text-xs uppercase tracking-[0.2em] text-dim mb-1">Should Have Notified</p>
          <p className="text-sm text-bleed">
            {missedWarranted.map((n) => n.party_name).join(", ")}
          </p>
        </div>
      )}

      {/* Techniques Encountered — every stage.mitre_technique that fired
          this run (verb_engine.RunState.encountered_technique_ids via
          action_run_store's techniques_encountered), regardless of outcome:
          this is exposure, not mastery, matching the backend's "deliberately
          NOT gated on penalties/outcome" framing. Full incident-narrative/
          source-citation content lives on the Dossier page (GET
          /dossier/me) — this is just enough to say what happened, one line
          each. */}
      {summary.techniques_encountered.length > 0 && (
        <div className="mb-6 max-w-sm text-left">
          <p className="font-term text-xs uppercase tracking-[0.2em] text-dim mb-2 text-center">
            Techniques Encountered
          </p>
          <ul className="space-y-2">
            {summary.techniques_encountered.map((t) => (
              <li key={t.technique_id}>
                <p className="text-sm text-white font-bold">{t.name}</p>
                <p className="text-xs text-dim">{t.description}</p>
              </li>
            ))}
          </ul>
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
