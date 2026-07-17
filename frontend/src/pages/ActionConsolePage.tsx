import { useNavigate, useParams } from "react-router-dom";
import ActionConsole from "../components/ActionConsole";

/**
 * Phase 2 Item 5 — solo/individual scenario runs (mode="scenario",
 * 10-minute "Compressed Run" cap). Deliberately its OWN page + WS system
 * (/ws/run/{runId}), separate from SimulationRoomPage.tsx's org-tabletop
 * flow (/ws/session/{sessionId}) — mirrors Arena mode's own precedent
 * (ArenaMatchPage.tsx) rather than branching inside the tabletop page, per
 * REVIEW_CRITERIA.md's isolation rule (d).
 */
export default function ActionConsolePage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();

  if (!runId) return null;

  return (
    <div className="h-[calc(100vh-0px)] flex flex-col">
      <ActionConsole runId={runId} />
      <div className="shrink-0 p-3 bg-panel border-t border-dim/20 text-center">
        <button
          onClick={() => navigate("/scenarios")}
          className="text-xs text-dim hover:text-white active:scale-95"
        >
          ← Back to Scenarios
        </button>
      </div>
    </div>
  );
}
