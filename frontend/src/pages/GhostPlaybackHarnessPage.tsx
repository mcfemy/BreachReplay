import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import GhostPlayback from "../components/GhostPlayback";
import { sampleGhostDto } from "../lib/ghostPlayback.fixture";
import type { GhostDto } from "../lib/ghostPlayback";
import { axiosInstance } from "../lib/api";

/**
 * Visual harness for Phase 4 ghost playback — NOT product UI.
 *
 * Open `/dev/ghost-playback` (optionally `?token=<share_token>` to load a
 * real GET /action-runs/public/ghost/{token} DTO). Drag the scrubber to
 * drive the live elapsed clock and watch the ghost map + feed advance.
 * Without a token, a built-in fixture DTO is used so you can look without
 * a backend ghost row.
 */
export default function GhostPlaybackHarnessPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(false);

  const remote = useQuery({
    queryKey: ["dev-ghost", token],
    enabled: !!token,
    queryFn: async () => {
      const { data } = await axiosInstance.get<GhostDto>(
        `/action-runs/public/ghost/${token}`,
      );
      return data;
    },
  });

  const ghost: GhostDto = useMemo(() => {
    if (remote.data) return remote.data;
    return sampleGhostDto();
  }, [remote.data]);

  const maxElapsed = Math.max(
    ghost.duration_seconds,
    ...ghost.map_frames.map((f) => f.elapsed_seconds),
    ...ghost.verb_timeline.map((v) => v.elapsed_seconds),
    60,
  );

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setElapsed((n) => (n >= maxElapsed ? n : n + 1));
    }, 250);
    return () => clearInterval(id);
  }, [playing, maxElapsed]);

  useEffect(() => {
    if (playing && elapsed >= maxElapsed) setPlaying(false);
  }, [playing, elapsed, maxElapsed]);

  return (
    <div className="min-h-screen bg-void text-white p-6 max-w-3xl mx-auto space-y-4">
      <header>
        <p className="text-[10px] text-phosphor uppercase tracking-widest font-extrabold">
          Dev harness — ghost playback
        </p>
        <h1 className="font-display text-xl font-bold mt-1">GhostPlayback visual check</h1>
        <p className="text-sm text-dim mt-1">
          Not wired into Daily/Scenario yet. Scrub the live clock or play. Optional{" "}
          <code className="text-phosphor">?token=</code> loads a real public ghost DTO.
        </p>
      </header>

      {token && remote.isLoading && (
        <p className="text-sm text-dim">Loading ghost for token…</p>
      )}
      {token && remote.isError && (
        <p className="text-sm text-bleed">Failed to load ghost for that token (404 or network).</p>
      )}

      <div className="bg-panel border border-white/10 rounded-lg overflow-hidden">
        <GhostPlayback ghost={ghost} elapsedSeconds={elapsed} mapClassName="w-full h-72 px-2 pb-2" />
      </div>

      <div className="space-y-2">
        <label className="block text-[10px] text-dim uppercase tracking-widest">
          Live elapsed clock — {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")} /{" "}
          {Math.floor(maxElapsed / 60)}:{String(maxElapsed % 60).padStart(2, "0")}
        </label>
        <input
          type="range"
          min={0}
          max={maxElapsed}
          value={Math.min(elapsed, maxElapsed)}
          onChange={(e) => {
            setPlaying(false);
            setElapsed(Number(e.target.value));
          }}
          className="w-full accent-phosphor"
          data-testid="ghost-harness-scrubber"
        />
        <div className="flex gap-2">
          <button
            type="button"
            className="px-3 py-1.5 text-xs bg-phosphor text-void font-bold rounded"
            onClick={() => setPlaying((p) => !p)}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            className="px-3 py-1.5 text-xs border border-white/20 rounded"
            onClick={() => {
              setPlaying(false);
              setElapsed(0);
            }}
          >
            Reset
          </button>
        </div>
        <p className="text-[10px] text-dim font-term">
          race_type={ghost.race_type} · frames={ghost.map_frames.length} · verbs=
          {ghost.verb_timeline.length}
          {token ? ` · token=${token}` : " · fixture DTO"}
        </p>
      </div>
    </div>
  );
}
