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
      navigate(`/session/${session.id}`);
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
        </div>

        {/* Search mode banner when AI is active */}
        {semantic && (
          <div className="mb-3 flex items-center gap-2 bg-breach-blue/10 border border-breach-blue/30 rounded px-3 py-2">
            <span className="text-breach-blue text-[10px] font-bold uppercase tracking-widest">⬡ AI Semantic Search Active</span>
            <span className="text-breach-muted text-[10px]">— describe a scenario in plain language and AI finds the closest match</span>
            <button onClick={handleToggleSemantic} className="ml-auto text-[10px] text-breach-muted hover:text-breach-accent uppercase tracking-wider">✕ Disable</button>
          </div>
        )}

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
          <div className="text-breach-muted text-sm">Loading scenarios...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {scenarios.map((s) => (
              <div key={s.id} className="bg-breach-surface border border-breach-border rounded p-4 hover:border-breach-blue transition-colors">
                <div className="flex items-start justify-between mb-2">
                  <span className="text-xs text-breach-muted uppercase tracking-wider">{s.source_type}</span>
                  <span className={`text-xs font-bold uppercase ${SEVERITY_COLOR[s.difficulty] || "text-breach-muted"}`}>
                    {s.difficulty}
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-breach-text mb-2 leading-snug">{s.title}</h3>
                <div className="flex flex-wrap gap-1 mb-3">
                  {s.mitre_techniques?.slice(0, 3).map((t) => (
                    <span key={t} className="text-xs bg-breach-bg border border-breach-border px-1.5 py-0.5 rounded text-breach-muted">{t}</span>
                  ))}
                </div>
                <div className="flex items-center justify-between text-xs text-breach-muted mb-3">
                  <span>{s.estimated_minutes}m</span>
                  <span>{s.industry_vertical || "—"}</span>
                  <span>{s.play_count} plays</span>
                </div>
                <button
                  onClick={() => launchScenario(s.id)}
                  className="w-full bg-breach-accent hover:bg-red-600 text-white py-1.5 rounded text-xs uppercase tracking-widest transition-colors"
                >
                  Launch Simulation
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
