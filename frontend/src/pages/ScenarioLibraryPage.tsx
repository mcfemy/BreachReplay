import { useEffect, useState } from "react";
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
  const navigate = useNavigate();

  useEffect(() => {
    fetchScenarios();
  }, [search, industry, difficulty]);

  async function fetchScenarios() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (industry) params.set("industry", industry);
      if (difficulty) params.set("difficulty", difficulty);
      const data = await api.get<Scenario[]>(`/scenarios?${params.toString()}`);
      setScenarios(data);
    } catch {
    } finally {
      setLoading(false);
    }
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
            <p className="text-breach-muted text-xs mt-1">{scenarios.length} scenarios available</p>
          </div>
        </div>

        <div className="flex gap-3 mb-6">
          <input
            placeholder="Search scenarios..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none focus:border-breach-blue"
          />
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
