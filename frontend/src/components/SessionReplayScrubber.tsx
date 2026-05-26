import { useState, useEffect, useRef } from "react";

interface Decision {
  gate_id: string;
  team_choice: string;
  correct_choice: string;
  is_correct: boolean;
  impact: string;
  nist_ref: string;
  explanation: string;
}

interface SessionReplayScrubberProps {
  decisions: Decision[];
}

export default function SessionReplayScrubber({ decisions }: SessionReplayScrubberProps) {
  const [activeIndex, setActiveIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const playInterval = useRef<any>(null);

  useEffect(() => {
    if (isPlaying) {
      playInterval.current = setInterval(() => {
        setActiveIndex((prev) => Math.min(prev + 1, decisions.length - 1));
      }, 5000);
    } else {
      if (playInterval.current) clearInterval(playInterval.current);
    }

    return () => {
      if (playInterval.current) clearInterval(playInterval.current);
    };
  }, [isPlaying, decisions.length]);

  // Stop playback when the last decision is reached
  useEffect(() => {
    if (isPlaying && activeIndex >= decisions.length - 1) {
      setIsPlaying(false);
    }
  }, [activeIndex, decisions.length, isPlaying]);

  if (!decisions || decisions.length === 0) {
    return (
      <div className="bg-breach-surface border border-breach-border rounded p-6 text-center text-xs text-breach-muted">
        No decision milestones recorded to play back.
      </div>
    );
  }

  const activeDecision = decisions[activeIndex];

  // Helper to generate realistic-looking SIEM logs related to the selected gate
  const getMockSIEMLogs = (decision: Decision) => {
    const timestamp = new Date().toLocaleTimeString();
    return [
      `[${timestamp}] INFO  - SYSTEM-GATEWAY :: Triage analysis on node ${decision.gate_id}`,
      `[${timestamp}] WARN  - FIREWALL-IDS  :: Detected suspicious inbound route mapping to NIST control: ${decision.nist_ref}`,
      `[${timestamp}] DECRYPT - LOG-PARSER  :: Analyst decision verified: "${decision.team_choice.slice(0, 50)}..."`,
      `[${timestamp}] AUDIT - SEC-COMPLY   :: Outcome recorded as ${decision.is_correct ? "SUCCESS" : "CRITICAL_GAP"}`,
      `[${timestamp}] SYSTEM - STATE_SYNC  :: Applying downstream impact: "${decision.impact.slice(0, 60)}..."`,
    ];
  };

  return (
    <div className="bg-breach-surface border border-breach-border rounded-lg p-6 relative overflow-hidden backdrop-blur-md">
      <div className="absolute top-0 right-0 w-64 h-64 bg-breach-blue/5 rounded-full blur-3xl pointer-events-none" />

      {/* Title */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6 border-b border-breach-border/60 pb-4">
        <div>
          <span className="text-[10px] text-breach-blue uppercase tracking-widest font-extrabold block mb-1">
            Tactical Incident Replayer
          </span>
          <h3 className="text-sm font-bold uppercase tracking-wider text-breach-text">
            Post-Simulation Replay Scrubber Timeline
          </h3>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setIsPlaying(!isPlaying)}
            className={`flex items-center gap-2 px-4 py-1.5 rounded text-xs uppercase tracking-wider font-bold transition-all duration-300 ${
              isPlaying
                ? "bg-breach-yellow text-black shadow-[0_0_15px_rgba(234,179,8,0.2)]"
                : "bg-breach-blue text-white shadow-[0_0_15px_rgba(59,130,246,0.2)]"
            }`}
          >
            {isPlaying ? (
              <>
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zM7 8a1 1 0 012 0v4a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                Pause Replay
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" />
                </svg>
                Play Replay
              </>
            )}
          </button>
        </div>
      </div>

      {/* Scrub Slider Track */}
      <div className="mb-8 relative px-4">
        {/* Connection Line */}
        <div className="absolute top-1/2 left-0 right-0 h-0.5 bg-breach-border -translate-y-1/2" />
        <div
          className="absolute top-1/2 left-0 h-0.5 bg-breach-blue -translate-y-1/2 transition-all duration-500"
          style={{ width: `${(activeIndex / (decisions.length - 1 || 1)) * 100}%` }}
        />

        {/* Nodes */}
        <div className="flex justify-between items-center relative z-10">
          {decisions.map((dec, idx) => {
            const isActive = idx === activeIndex;
            const isPassed = idx < activeIndex;

            return (
              <div key={dec.gate_id} className="flex flex-col items-center">
                <button
                  onClick={() => {
                    setIsPlaying(false);
                    setActiveIndex(idx);
                  }}
                  className={`w-8 h-8 rounded-full border flex items-center justify-center font-bold text-xs transition-all duration-300 hover:scale-110 ${
                    isActive
                      ? "bg-breach-blue text-black border-breach-blue shadow-[0_0_15px_rgba(59,130,246,0.5)] ring-4 ring-breach-blue/20"
                      : isPassed
                      ? "bg-slate-900 text-breach-blue border-breach-blue"
                      : "bg-[#0a0e1a] text-breach-muted border-breach-border hover:border-breach-muted"
                  }`}
                >
                  {idx + 1}
                </button>
                <span
                  className={`text-[9px] uppercase tracking-wider font-semibold mt-2 px-1 rounded block ${
                    isActive ? "text-breach-blue font-bold" : "text-breach-muted"
                  }`}
                >
                  {dec.gate_id.slice(0, 10)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Replay Console Frame and Details */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Terminal SIEM Replayer */}
        <div className="bg-[#050810] border border-breach-border rounded p-4 flex flex-col justify-between h-64">
          <div className="flex items-center justify-between border-b border-breach-border/60 pb-2 mb-3">
            <span className="text-[10px] text-breach-muted uppercase tracking-widest block">
              💻 Active SIEM Replayer
            </span>
            <span className="w-1.5 h-1.5 rounded-full bg-breach-blue animate-pulse" />
          </div>
          <div className="flex-1 space-y-2 overflow-y-auto font-mono text-[10px] text-slate-400">
            {getMockSIEMLogs(activeDecision).map((log, i) => (
              <div key={i} className="leading-relaxed hover:text-breach-text transition-colors">
                {log}
              </div>
            ))}
          </div>
          <div className="border-t border-breach-border/40 pt-2 text-[8px] text-breach-muted text-center uppercase tracking-wider">
            Replaying Frame {activeIndex + 1} of {decisions.length}
          </div>
        </div>

        {/* Tactical Decision State */}
        <div className="lg:col-span-2 bg-[#090d16]/60 border border-breach-border rounded p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-breach-border pb-3">
            <div>
              <span className="text-[10px] text-breach-muted uppercase tracking-widest">
                Milestone Action Summary
              </span>
              <h4 className="text-sm font-bold text-breach-text mt-0.5 uppercase tracking-wide">
                {activeDecision.gate_id}
              </h4>
            </div>
            <div className="flex gap-2">
              <span className="text-[10px] bg-slate-900 border border-breach-border px-2 py-0.5 rounded text-breach-blue font-bold font-mono">
                {activeDecision.nist_ref}
              </span>
              <span
                className={`text-[10px] border px-2 py-0.5 rounded font-bold uppercase tracking-wider ${
                  activeDecision.is_correct
                    ? "bg-green-500/10 border-green-500/30 text-green-400"
                    : "bg-breach-accent/10 border-breach-accent/30 text-breach-accent"
                }`}
              >
                {activeDecision.is_correct ? "✓ Correct Action" : "✗ Critical Gap"}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="space-y-1.5">
              <span className="text-breach-muted uppercase tracking-wider text-[9px] font-extrabold block">
                Team Action Chosen
              </span>
              <div className="bg-slate-950/40 border border-breach-border/60 px-3 py-2 rounded text-breach-text leading-relaxed">
                {activeDecision.team_choice}
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-breach-muted uppercase tracking-wider text-[9px] font-extrabold block">
                Correct NIST Strategy
              </span>
              <div className="bg-green-950/20 border border-green-500/20 px-3 py-2 rounded text-green-400 leading-relaxed">
                {activeDecision.correct_choice}
              </div>
            </div>
          </div>

          <div className="space-y-2 pt-3 border-t border-breach-border/50 text-xs leading-relaxed">
            <span className="text-breach-muted uppercase tracking-wider text-[9px] font-extrabold block">
              Downstream Containment Analysis
            </span>
            <p className="text-breach-text opacity-90">{activeDecision.impact}</p>
            <p className="text-breach-muted italic text-[11px] bg-slate-950/30 p-3 rounded border border-breach-border/40">
              [ANALYSIS] :: {activeDecision.explanation}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
