import { useEffect, useState, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useAuthStore } from "../store/auth";
import { useSimulationSocket } from "../lib/useSimulationSocket";
import { useSimStore, type Participant } from "../store/simulation";


interface SessionData {
  id: string;
  scenario_id: string;
  organization_id: string | null;
  host_user_id: string;
  status: string;
  mode: string;
  started_at: string | null;
  completed_at: string | null;
}

interface ScenarioData {
  id: string;
  title: string;
  description: string;
  difficulty: string;
  estimated_minutes: number;
}

const ROLE_METADATA: Record<
  string,
  { title: string; description: string; color: string; icon: string }
> = {
  incident_commander: {
    title: "Incident Commander",
    description: "Leads containment strategy and holds final decision lock-in authority.",
    color: "border-red-500 text-red-400 bg-red-950/20 shadow-[0_0_15px_rgba(239,68,68,0.1)]",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>`,
  },
  forensic_analyst: {
    title: "Forensic Analyst",
    description: "Analyzes host, disk, and memory captures to reconstruct attack chain.",
    color: "border-blue-500 text-blue-400 bg-blue-950/20 shadow-[0_0_15px_rgba(59,130,246,0.1)]",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" /></svg>`,
  },
  communications_lead: {
    title: "Communications Lead",
    description: "Coordinates customer notifications, legal disclosures, and public relations.",
    color: "border-yellow-500 text-yellow-400 bg-yellow-950/20 shadow-[0_0_15px_rgba(234,179,8,0.1)]",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" /></svg>`,
  },
  soc_analyst: {
    title: "SOC Analyst",
    description: "Monitors real-time SIEM alerts, triages host events, and proposes remediation.",
    color: "border-green-500 text-green-400 bg-green-950/20 shadow-[0_0_15px_rgba(34,197,94,0.1)]",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>`,
  },
  threat_intel_analyst: {
    title: "Threat Intel Analyst",
    description: "Tracks threat actor TTPs, attribution signals, and IOC feeds throughout the incident.",
    color: "border-purple-500 text-purple-400 bg-purple-950/20 shadow-[0_0_15px_rgba(168,85,247,0.1)]",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`,
  },
  legal_compliance: {
    title: "Legal / Compliance",
    description: "Advises on regulatory disclosure timelines, breach notification laws, and evidentiary handling.",
    color: "border-orange-500 text-orange-400 bg-orange-950/20 shadow-[0_0_15px_rgba(249,115,22,0.1)]",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" /></svg>`,
  },
  network_engineer: {
    title: "Network Engineer",
    description: "Executes firewall rule changes, VLAN isolation, and traffic captures during containment.",
    color: "border-cyan-500 text-cyan-400 bg-cyan-950/20 shadow-[0_0_15px_rgba(6,182,212,0.1)]",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" /></svg>`,
  },
  observer: {
    title: "Observer",
    description: "Spectates simulation flow. Has no voting or decision authority.",
    color: "border-slate-500 text-slate-400 bg-slate-800/40",
    icon: `<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>`,
  },
};

export default function SessionMultiplayerLobbyPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const { participants, reset } = useSimStore();

  const [session, setSessionData] = useState<SessionData | null>(null);
  const [scenario, setScenarioData] = useState<ScenarioData | null>(null);
  const [claimingRole, setClaimingRole] = useState<string | null>(null);
  const [error, setError] = useState<string>("");
  const [copied, setCopied] = useState<boolean>(false);
  const pollInterval = useRef<any>(null);

  // Connect to the WebSocket room using our custom hook; session-start navigation
  // is handled by the status polling below — no WS notification needed here.
  const { startStream } = useSimulationSocket(sessionId!);

  // Reset store to clear any stale simulation state
  useEffect(() => {
    reset();
    fetchSessionDetails();

    // Set up polling interval to check if session status changes to 'active'
    pollInterval.current = setInterval(async () => {
      try {
        const data = await api.get<SessionData>(`/sessions/${sessionId}`);
        if (data.status === "active") {
          navigate(`/session/${sessionId}`);
        }
      } catch {
        // Suppress errors during polling
      }
    }, 2000);

    return () => {
      if (pollInterval.current) clearInterval(pollInterval.current);
    };
  }, [sessionId]);

  async function fetchSessionDetails() {
    try {
      const sData = await api.get<SessionData>(`/sessions/${sessionId}`);
      setSessionData(sData);

      if (sData.status === "active") {
        navigate(`/session/${sessionId}`);
        return;
      }

      const scData = await api.get<ScenarioData>(`/scenarios/${sData.scenario_id}`);
      setScenarioData(scData);
    } catch (err: any) {
      setError(err.message || "Failed to load session details");
    }
  }

  async function handleClaimRole(role: string) {
    setError("");
    setClaimingRole(role);
    try {
      await api.post(`/sessions/${sessionId}/join`, { role });
      // Reload session/participants state
      fetchSessionDetails();
    } catch (err: any) {
      setError(err.message || `Failed to claim role ${role}`);
    } finally {
      setClaimingRole(null);
    }
  }

  async function handleCommenceOperations() {
    setError("");
    try {
      await api.post(`/sessions/${sessionId}/start`, {});
      startStream();
      navigate(`/session/${sessionId}`);
    } catch (err: any) {
      setError(err.message || "Failed to start incident operations");
    }
  }

  function handleCopyInvite() {
    const inviteUrl = window.location.href;
    navigator.clipboard.writeText(inviteUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // Find who has claimed each role
  const claimedSeats: Record<string, Participant | null> = {
    incident_commander: null,
    forensic_analyst: null,
    communications_lead: null,
    soc_analyst: null,
    threat_intel_analyst: null,
    legal_compliance: null,
    network_engineer: null,
    observer: null,
  };

  participants.forEach((p) => {
    // Standard analysts and roles
    if (p.role in claimedSeats) {
      // If observer, multiple people can be observers, but let's keep track of the most recent or list them
      if (p.role === "observer") {
        claimedSeats.observer = p; // simplified representation
      } else {
        claimedSeats[p.role] = p;
      }
    }
  });

  const isHost = session?.host_user_id === user?.id;
  const myRole = participants.find((p) => p.user_id === user?.id)?.role || "None Assigned";

  return (
    <div className="min-h-screen bg-breach-bg text-breach-text flex flex-col p-6 font-mono selection:bg-breach-accent/30 selection:text-white">
      {/* Header bar */}
      <header className="max-w-7xl mx-auto w-full border-b border-breach-border pb-4 mb-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <span className="text-breach-accent text-xs font-bold uppercase tracking-widest block mb-1">
            CYBER TACTICAL OPERATIONS CENTRE
          </span>
          <h1 className="text-xl font-bold uppercase tracking-wider text-breach-text">
            Incident Response Multiplayer Lobby
          </h1>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleCopyInvite}
            className="flex items-center gap-2 bg-breach-surface hover:bg-slate-800 border border-breach-border px-4 py-2 rounded text-xs transition-all duration-300 uppercase font-bold text-breach-blue hover:border-breach-blue"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"
              />
            </svg>
            {copied ? "Link Copied!" : "Copy Invite Link"}
          </button>
          <button
            onClick={() => navigate("/scenarios")}
            className="bg-breach-surface hover:bg-slate-800 border border-breach-border px-4 py-2 rounded text-xs transition-all duration-300 uppercase font-bold text-breach-muted"
          >
            Leave
          </button>
        </div>
      </header>

      {error && (
        <div className="max-w-7xl mx-auto w-full mb-6 bg-red-950/40 border border-breach-accent text-breach-accent px-4 py-3 rounded text-xs">
          [ERROR] :: {error}
        </div>
      )}

      <main className="max-w-7xl mx-auto w-full flex-1 grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* Left column: scenario details and roles board */}
        <section className="lg:col-span-3 space-y-8">
          {/* Scenario Profile Block */}
          {scenario && (
            <div className="bg-breach-surface/80 border border-breach-border rounded-lg p-6 relative overflow-hidden backdrop-blur-md">
              <div className="absolute top-0 right-0 w-64 h-64 bg-breach-blue/5 rounded-full blur-3xl pointer-events-none" />
              <div className="flex items-center gap-3 mb-2">
                <span className="bg-breach-blue/15 text-breach-blue px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-widest">
                  MULTIPLAYER MODE
                </span>
                <span className="text-xs text-breach-muted">|</span>
                <span className="text-xs uppercase tracking-wider text-breach-yellow">
                  Difficulty: {scenario.difficulty}
                </span>
              </div>
              <h2 className="text-lg font-bold text-breach-text leading-snug uppercase mb-2">
                {scenario.title}
              </h2>
              <p className="text-xs text-breach-muted leading-relaxed max-w-3xl">
                {scenario.description}
              </p>
              <div className="mt-4 flex gap-6 text-xs text-breach-muted">
                <div>
                  ESTIMATED TIMELINE:{" "}
                  <span className="text-breach-text font-bold">{scenario.estimated_minutes} Min</span>
                </div>
                <div>
                  YOUR CURRENT SEAT:{" "}
                  <span className="text-breach-accent font-bold uppercase">{myRole}</span>
                </div>
              </div>
            </div>
          )}

          {/* Interactive Role Desks selection board */}
          <div>
            <h2 className="text-xs text-breach-muted uppercase tracking-widest mb-4">
              🛡️ Claim Your Incident Containment Desk
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {Object.entries(ROLE_METADATA).map(([roleKey, meta]) => {
                const occupant = claimedSeats[roleKey];
                const isClaimedByMe = occupant?.user_id === user?.id;
                const isSeatTaken = occupant !== null && occupant !== undefined;

                return (
                  <div
                    key={roleKey}
                    onClick={() =>
                      !isClaimedByMe &&
                      (!isSeatTaken || roleKey === "observer") &&
                      handleClaimRole(roleKey)
                    }
                    className={`border rounded-lg p-5 transition-all duration-300 group select-none relative ${
                      isClaimedByMe
                        ? "border-breach-blue bg-breach-surface shadow-[0_0_15px_rgba(59,130,246,0.15)] ring-1 ring-breach-blue"
                        : isSeatTaken && roleKey !== "observer"
                        ? "border-breach-border bg-slate-950/40 cursor-not-allowed opacity-60"
                        : "border-breach-border bg-breach-surface hover:border-breach-blue cursor-pointer hover:shadow-[0_0_15px_rgba(59,130,246,0.08)]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4 mb-3">
                      <div className="flex items-center gap-3">
                        <div
                          className={`p-2 rounded border ${meta.color}`}
                          dangerouslySetInnerHTML={{ __html: meta.icon }}
                        />
                        <div>
                          <h3 className="text-sm font-bold text-breach-text tracking-wide group-hover:text-breach-blue transition-colors">
                            {meta.title}
                          </h3>
                          <span className="text-[10px] text-breach-muted uppercase block">
                            {roleKey === "observer" ? "Unlimited Slots" : "1 Seat Available"}
                          </span>
                        </div>
                      </div>
                      <div>
                        {isClaimedByMe ? (
                          <span className="bg-breach-blue text-black px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider animate-pulse">
                            My Desk
                          </span>
                        ) : isSeatTaken && roleKey !== "observer" ? (
                          <span className="bg-red-950/40 border border-breach-accent/40 text-breach-accent px-2 py-0.5 rounded text-[10px] font-bold uppercase">
                            Seat Taken
                          </span>
                        ) : claimingRole === roleKey ? (
                          <span className="bg-slate-900 border border-breach-blue text-breach-blue px-2 py-0.5 rounded text-[10px] font-bold uppercase animate-pulse">
                            Claiming...
                          </span>
                        ) : (
                          <span className="bg-slate-900 border border-breach-border group-hover:border-breach-blue text-breach-muted group-hover:text-breach-blue px-2 py-0.5 rounded text-[10px] font-bold uppercase transition-all duration-300">
                            Claim Seat
                          </span>
                        )}
                      </div>
                    </div>

                    <p className="text-xs text-breach-muted leading-relaxed mb-4">
                      {meta.description}
                    </p>

                    {/* Occupant details */}
                    {isSeatTaken && (
                      <div className="border-t border-breach-border/50 pt-3 flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-breach-green animate-pulse" />
                        <span className="text-xs text-breach-text font-bold">
                          {occupant.name} {isClaimedByMe && "(You)"}
                        </span>
                        <span className="text-[10px] text-breach-muted uppercase font-semibold">
                          [Active Analyst]
                        </span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* Right column: active online roster & controls */}
        <aside className="space-y-8">
          {/* Active online roster */}
          <div className="bg-breach-surface/80 border border-breach-border rounded-lg p-5 flex flex-col h-96 overflow-hidden">
            <h3 className="text-xs text-breach-muted uppercase tracking-widest border-b border-breach-border pb-3 mb-4">
              📡 Operations Roster ({participants.length})
            </h3>
            <div className="flex-1 overflow-y-auto space-y-3">
              {participants.map((p) => {
                const meta = ROLE_METADATA[p.role];
                return (
                  <div
                    key={p.user_id}
                    className="flex items-center justify-between gap-3 text-xs bg-slate-950/40 p-2.5 rounded border border-breach-border/50"
                  >
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-2 h-2 rounded-full ${
                          p.online ? "bg-breach-green animate-pulse" : "bg-slate-700"
                        }`}
                      />
                      <div>
                        <div className="font-bold text-breach-text">{p.name}</div>
                        <div className="text-[10px] text-breach-muted uppercase tracking-wider">
                          {meta?.title || p.role}
                        </div>
                      </div>
                    </div>
                    <span
                      className={`text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase ${
                        p.online
                          ? "bg-breach-green/10 text-breach-green border border-breach-green/20"
                          : "bg-slate-900 text-slate-500"
                      }`}
                    >
                      {p.online ? "Online" : "Offline"}
                    </span>
                  </div>
                );
              })}
              {participants.length === 0 && (
                <div className="text-xs text-breach-muted text-center py-8">
                  Awaiting analyst websocket connections...
                </div>
              )}
            </div>
          </div>

          {/* Action Launch Board */}
          <div className="bg-breach-surface/80 border border-breach-border rounded-lg p-5">
            <h4 className="text-xs text-breach-muted uppercase tracking-widest mb-3">
              🕹️ Incident Launch Panel
            </h4>
            {isHost ? (
              <div className="space-y-3">
                <p className="text-[10px] text-breach-muted leading-relaxed">
                  As the Host, you hold final clearance to commence simulation alert streams and
                  initiate incident containment desks.
                </p>
                <button
                  onClick={handleCommenceOperations}
                  className="w-full bg-breach-green hover:bg-green-600 text-black py-2.5 rounded text-xs uppercase tracking-widest font-bold transition-all duration-300 shadow-[0_0_15px_rgba(34,197,94,0.2)] hover:scale-[1.02]"
                >
                  Commence IR Operations
                </button>
              </div>
            ) : (
              <div className="text-center py-2">
                <div className="flex items-center justify-center gap-2 mb-2">
                  <div className="w-2 h-2 rounded-full bg-breach-yellow animate-ping" />
                  <span className="text-xs text-breach-yellow font-bold uppercase tracking-wider">
                    Securing Clearances...
                  </span>
                </div>
                <p className="text-[10px] text-breach-muted leading-relaxed">
                  Awaiting Host authorization to initiate cyber alert sequences. Claim your role card
                  and prepare containment playbooks.
                </p>
              </div>
            )}
          </div>
        </aside>
      </main>
    </div>
  );
}
