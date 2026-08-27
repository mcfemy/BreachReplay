import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ActionConsole from "../components/ActionConsole";
import { clearRaceGhost, loadRaceGhost } from "../lib/ghostRace";
import type { GhostDto } from "../lib/ghostPlayback";

/**
 * Phase 4 — live ghost race room.
 *
 * Same ActionConsole / WS loop as /run/:runId, with GhostPlayback stacked
 * (mobile) or side-by-side (md+) via the console's `ghost` prop. Ghost DTO
 * comes from POST /action-runs/race (stashed in sessionStorage) — not a
 * second GET /daily/ghost that could re-select a different board neighbor.
 */
export default function RaceRoomPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();

  const ghost: GhostDto | null = useMemo(
    () => (runId ? loadRaceGhost(runId) : null),
    [runId],
  );

  if (!runId) return null;

  if (!ghost) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6 bg-void text-white">
        <div className="text-center max-w-sm space-y-3">
          <h1 className="text-lg font-bold">Race session expired</h1>
          <p className="text-sm text-dim">
            The ghost payload for this race is gone (refresh or a new tab). Start again from Daily debrief or a share link.
          </p>
          <Link to="/daily" className="text-sm text-phosphor hover:text-white">
            ← Back to Daily
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-0px)] flex flex-col" data-testid="race-room">
      <div className="shrink-0 border-b border-dim/20 px-4 py-2 flex items-center justify-between bg-panel">
        <span className="text-[10px] text-phosphor uppercase tracking-widest font-extrabold">
          Ghost race
        </span>
        <span className="text-[10px] text-dim truncate max-w-[50%]">
          vs {ghost.player_label} · {ghost.scenario_title}
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <ActionConsole
          runId={runId}
          ghost={ghost}
          onComplete={() => {
            clearRaceGhost(runId);
          }}
        />
      </div>
      <div className="shrink-0 p-3 bg-panel border-t border-dim/20 text-center">
        <button
          type="button"
          onClick={() => {
            clearRaceGhost(runId);
            navigate("/scenarios");
          }}
          className="text-xs text-dim hover:text-white active:scale-95"
        >
          ← Leave race
        </button>
      </div>
    </div>
  );
}
