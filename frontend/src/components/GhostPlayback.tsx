import NetworkMap from "./NetworkMap";
import AlertFeed from "./AlertFeed";
import {
  frameToNetworkMap,
  ghostVerbFeedLines,
  selectMapFrame,
  type GhostDto,
} from "../lib/ghostPlayback";

/**
 * Phase 4 — client ghost playback. Renders a second NetworkMap + feed
 * driven by a server ghost DTO and the *live* run's elapsed clock. No
 * fetch, no selection UI, no independent timer — the parent passes
 * `elapsedSeconds` from the live run (or a harness scrubber).
 *
 * Reuses NetworkMap (same fog / juice / reduced-motion) and AlertFeed
 * (same typewriter). Ghost finishes early → last frame holds; live
 * outlasts ghost → same. Spec §6 / PR #50 DTO.
 */

export interface GhostPlaybackProps {
  ghost: GhostDto;
  /** Live run (or harness) elapsed seconds — sole clock source. */
  elapsedSeconds: number;
  className?: string;
  mapClassName?: string;
}

export default function GhostPlayback({
  ghost,
  elapsedSeconds,
  className,
  mapClassName,
}: GhostPlaybackProps) {
  const frame = selectMapFrame(ghost.map_frames, elapsedSeconds);
  const feedLines = ghostVerbFeedLines(ghost.verb_timeline, elapsedSeconds);
  const map = frame ? frameToNetworkMap(frame) : null;
  const clock = `${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, "0")}`;

  return (
    <div
      className={className}
      data-testid="ghost-playback"
      data-race-type={ghost.race_type}
      data-elapsed={elapsedSeconds}
      aria-label={`Ghost playback — ${ghost.player_label}`}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-white/5">
        <p className="text-[10px] text-phosphor uppercase tracking-widest font-extrabold">
          Ghost — {ghost.player_label}
        </p>
        <p
          className="text-[11px] text-phosphor font-term tabular-nums"
          data-testid="ghost-clock"
          aria-live="off"
        >
          {clock}
        </p>
      </div>
      <div className="flex items-center justify-between gap-2 px-3 py-0.5">
        <p className="text-[10px] text-dim font-term truncate">
          {ghost.scenario_title}
          {ghost.containment_seconds != null
            ? ` · contained ${Math.floor(ghost.containment_seconds / 60)}:${String(ghost.containment_seconds % 60).padStart(2, "0")}`
            : ""}
        </p>
      </div>
      <AlertFeed lines={feedLines} />
      {map && map.nodes.length > 0 ? (
        <NetworkMap
          nodes={map.nodes}
          edges={map.edges}
          nodeStates={map.nodeStates}
          className={mapClassName ?? "w-full h-56"}
        />
      ) : (
        <p className="text-xs text-dim text-center py-8" data-testid="ghost-playback-empty">
          No ghost map frames.
        </p>
      )}
    </div>
  );
}
