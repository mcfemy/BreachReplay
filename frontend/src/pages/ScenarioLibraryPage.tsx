import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

interface Scenario {
  id: string;
  title: string;
  industry_vertical: string | null;
  difficulty: string;
  estimated_minutes: number;
  source_type: string;
  source_reference: string | null;
  mitre_techniques: string[] | null;
  regulatory_frameworks: string[] | null;
  play_count: number;
  avg_score: number | null;
}

const SEVERITY_COLOR: Record<string, string> = {
  awareness: "text-breach-green",
  practitioner: "text-breach-yellow",
  expert: "text-breach-accent",
};

export default function ScenarioLibraryPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [industry, setIndustry] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [semantic, setSemantic] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();

  // Debounced re-fetch on filter changes
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchScenarios(), semantic ? 0 : 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [search, industry, difficulty, semantic]);

  async function fetchScenarios() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (industry) params.set("industry", industry);
      if (difficulty) params.set("difficulty", difficulty);
      if (semantic && search) params.set("semantic", "true");
      const data = await api.get<Scenario[]>(`/scenarios?${params.toString()}`);
      setScenarios(data);
    } catch (err: any) {
      setScenarios([]);
    } finally {
      setLoading(false);
    }
  }

  function handleToggleSemantic() {
    setSemantic((v) => !v);
  }

  async function launchScenario(scenarioId: string) {
    try {
      const session = await api.post<{ id: string }>("/sessions", { scenario_id: scenarioId, mode: "solo" });
      navigate(`/session/${session.id}/intro`);
    } catch (err: any) {
      alert(err.message);
    }
  }

  return (
    <div className="min-h-screen bg-breach-bg p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-breach-text uppercase tracking-widest">Scenario Library</h1>
            <p className="text-breach-muted text-xs mt-1">
              {loading
                ? "Searching..."
                : search
                ? `${scenarios.length} result${scenarios.length !== 1 ? "s" : ""} for "${search}"`
                : `${scenarios.length} scenarios available`}
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <a href="/pricing" className="text-breach-muted hover:text-breach-text transition-colors uppercase tracking-wider">Pricing</a>
            <a href="/settings" className="text-breach-muted hover:text-breach-text transition-colors uppercase tracking-wider">Settings</a>
          </div>
        </div>

        {/* Search mode banner when AI is active */}
        {semantic && (
          <div className="mb-3 flex items-center gap-2 bg-breach-blue/10 border border-breach-blue/30 rounded px-3 py-2">
            <span className="text-breach-blue text-[10px] font-bold uppercase tracking-widest">⬡ AI Semantic Search Active</span>
            <span className="text-breach-muted text-[10px]">— describe a scenario in plain language and AI finds the closest match</span>
            <button onClick={handleToggleSemantic} className="ml-auto text-[10px] text-breach-muted hover:text-breach-accent uppercase tracking-wider">✕ Disable</button>
          </div>
        )}

        {/* Feature spotlight cards */}
        <div className="grid grid-cols-2 gap-3 mb-6">
          <button
            onClick={() => navigate("/daily")}
            className="group relative overflow-hidden border border-orange-500/30 bg-orange-500/5 hover:bg-orange-500/10 rounded-xl p-4 text-left transition-all hover:border-orange-500/50"
          >
            <div className="flex items-start gap-3">
              <span className="text-3xl">🔐</span>
              <div>
                <div className="text-xs text-orange-400 uppercase tracking-widest font-bold mb-0.5">Daily Breach</div>
                <div className="text-sm font-bold text-white group-hover:text-orange-200 transition-colors">Today's Incident</div>
                <div className="text-xs text-gray-500 mt-1">10 min · One shot · Global leaderboard</div>
              </div>
            </div>
            <div className="absolute right-3 top-3 text-orange-600 group-hover:text-orange-400 transition-colors text-lg">→</div>
          </button>
          <button
            onClick={() => navigate("/redteam")}
            className="group relative overflow-hidden border border-red-500/30 bg-red-500/5 hover:bg-red-500/10 rounded-xl p-4 text-left transition-all hover:border-red-500/50"
          >
            <div className="flex items-start gap-3">
              <span className="text-3xl">🔴</span>
              <div>
                <div className="text-xs text-red-400 uppercase tracking-widest font-bold mb-0.5">Red Team Mode</div>
                <div className="text-sm font-bold text-white group-hover:text-red-200 transition-colors">Play the Attacker</div>
                <div className="text-xs text-gray-500 mt-1">Choose TTPs · Evade blue team · Strike</div>
              </div>
            </div>
            <div className="absolute right-3 top-3 text-red-600 group-hover:text-red-400 transition-colors text-lg">→</div>
          </button>
        </div>

        <div className="flex gap-3 mb-6">
          <div className="flex-1 relative">
            <input
              placeholder={semantic ? "Describe the breach, e.g. 'ransomware encrypting hospital backups'..." : "Search scenarios by title..."}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchScenarios()}
              className={`w-full bg-breach-surface border text-breach-text px-3 py-2 rounded text-sm focus:outline-none pr-32 transition-colors ${
                semantic ? "border-breach-blue focus:border-breach-blue" : "border-breach-border focus:border-breach-blue"
              }`}
            />
            <button
              onClick={handleToggleSemantic}
              title={semantic ? "Click to disable AI semantic search" : "Click to enable AI semantic search"}
              className={`absolute right-2 top-1/2 -translate-y-1/2 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider transition-all ${
                semantic
                  ? "bg-breach-blue text-black"
                  : "bg-breach-surface border border-breach-border text-breach-muted hover:border-breach-blue hover:text-breach-blue"
              }`}
            >
              {semantic ? "⬡ AI: ON" : "⬡ AI: OFF"}
            </button>
          </div>
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none"
          >
            <option value="">All Industries</option>
            <option value="healthcare">Healthcare</option>
            <option value="energy">Energy</option>
            <option value="finance">Finance</option>
            <option value="government">Government</option>
            <option value="technology">Technology</option>
            <option value="hospitality">Hospitality</option>
            <option value="supply_chain">Supply Chain</option>
            <option value="critical_infrastructure">Critical Infrastructure</option>
          </select>
          <select
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
            className="bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none"
          >
            <option value="">All Difficulties</option>
            <option value="awareness">Awareness</option>
            <option value="practitioner">Practitioner</option>
            <option value="expert">Expert</option>
          </select>
        </div>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 text-breach-muted">
            <div className="w-8 h-8 border-2 border-breach-accent border-t-transparent rounded-full animate-spin mb-3"></div>
            <span className="text-sm uppercase tracking-widest">Loading scenarios...</span>
          </div>
        ) : scenarios.length === 0 ? (
          <div className="text-center py-20 text-breach-muted">
            <div className="text-4xl mb-3">⚡</div>
            <p className="text-sm uppercase tracking-widest">No scenarios match your filters</p>
            <button onClick={() => { setSearch(""); setIndustry(""); setDifficulty(""); }} className="mt-4 text-xs text-breach-blue hover:underline">Clear filters</button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {scenarios.map((s) => (
              <div key={s.id} className="bg-breach-surface border border-breach-border rounded p-4 hover:border-breach-blue transition-all flex flex-col">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] text-breach-muted uppercase tracking-widest border border-breach-border px-1.5 py-0.5 rounded">
                      {s.source_type.replace(/_/g, " ")}
                    </span>
                    {s.industry_vertical && (
                      <span className="text-[9px] text-breach-blue uppercase tracking-widest border border-breach-blue/30 px-1.5 py-0.5 rounded">
                        {s.industry_vertical.replace(/_/g, " ")}
                      </span>
                    )}
                  </div>
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${SEVERITY_COLOR[s.difficulty] || "text-breach-muted"}`}>
                    {s.difficulty}
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-breach-text mb-3 leading-snug flex-1">{s.title}</h3>
                <div className="flex flex-wrap gap-1 mb-3">
                  {s.mitre_techniques?.slice(0, 4).map((t) => (
                    <span key={t} className="text-[9px] bg-breach-bg border border-breach-border px-1.5 py-0.5 rounded text-breach-muted font-mono">{t}</span>
                  ))}
                  {(s.mitre_techniques?.length ?? 0) > 4 && (
                    <span className="text-[9px] text-breach-muted">+{(s.mitre_techniques?.length ?? 0) - 4} more</span>
                  )}
                </div>
                <div className="flex items-center justify-between text-[10px] text-breach-muted mb-4 border-t border-breach-border/40 pt-3">
                  <span className="flex items-center gap-1">⏱ {s.estimated_minutes}m</span>
                  <span className="flex items-center gap-1">▶ {s.play_count} plays</span>
                  {s.avg_score != null && (
                    <span className={`flex items-center gap-1 font-bold ${s.avg_score >= 80 ? "text-green-400" : s.avg_score >= 60 ? "text-yellow-400" : "text-breach-accent"}`}>
                      avg {s.avg_score.toFixed(0)}%
                    </span>
                  )}
                </div>
                <button
                  onClick={() => launchScenario(s.id)}
                  className="w-full bg-breach-accent hover:bg-red-600 text-white py-2 rounded text-xs uppercase tracking-widest transition-colors font-bold"
                >
                  Launch Simulation →
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
