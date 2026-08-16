import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

// Mirrors dossier_service.compute_user_dossier's response shape exactly
// (backend/app/services/dossier_service.py) — every technique in
// TECHNIQUE_DOSSIER is always present, `encountered: false` and no
// incident_narrative/source_reference content shown for ones this user
// hasn't hit yet, so the full 30-entry dossier renders with locked slots
// rather than just the encountered subset.
interface DossierTechnique {
  technique_id: string;
  name: string;
  tactic: string;
  description: string;
  incident_narrative: string;
  source_reference: string;
  scenarios: string[];
  encountered: boolean;
  encounter_count: number;
  first_encountered_at: string | null;
  last_encountered_at: string | null;
}

interface DossierData {
  techniques: Record<string, DossierTechnique>;
  total_techniques: number;
  encountered_count: number;
}

function EncounteredCard({ t }: { t: DossierTechnique }) {
  return (
    <div className="bg-breach-bg border border-breach-border rounded-lg p-3">
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="text-sm font-bold text-breach-text">{t.name}</span>
        <span className="shrink-0 text-[9px] font-mono text-breach-muted">{t.technique_id}</span>
      </div>
      <p className="text-[10px] text-breach-muted leading-snug mb-2">{t.description}</p>
      <p className="text-[10px] text-gray-400 leading-snug italic mb-2">{t.incident_narrative}</p>
      <div className="flex items-center justify-between gap-2 pt-2 border-t border-white/5">
        <span className="text-[9px] text-gray-600">{t.source_reference}</span>
        <span className="text-[9px] text-breach-accent shrink-0">
          Encountered {t.encounter_count}×
        </span>
      </div>
    </div>
  );
}

function LockedCard({ t }: { t: DossierTechnique }) {
  return (
    <div className="bg-breach-bg border border-breach-border rounded-lg p-3 opacity-40">
      <div className="flex items-center gap-2">
        <span className="text-base grayscale shrink-0" aria-hidden="true">🔒</span>
        <span className="text-sm font-bold text-gray-500 blur-[3px] select-none">{t.name}</span>
      </div>
    </div>
  );
}

function TacticGroup({ tactic, techniques }: { tactic: string; techniques: DossierTechnique[] }) {
  const sorted = [...techniques].sort((a, b) => a.technique_id.localeCompare(b.technique_id));
  return (
    <div className="bg-breach-surface border border-breach-border rounded-xl p-4">
      <h2 className="text-xs font-bold text-breach-muted uppercase tracking-widest mb-3">{tactic}</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {sorted.map((t) =>
          t.encountered ? <EncounteredCard key={t.technique_id} t={t} /> : <LockedCard key={t.technique_id} t={t} />,
        )}
      </div>
    </div>
  );
}

export default function DossierPage() {
  const { data, isLoading, isError } = useQuery<DossierData>({
    queryKey: ["my-dossier"],
    queryFn: () => api.get<DossierData>("/dossier/me"),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen bg-breach-bg flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="min-h-screen bg-breach-bg p-6 flex items-center justify-center text-breach-muted">
        Could not load your dossier.
      </div>
    );
  }

  const groups = new Map<string, DossierTechnique[]>();
  for (const t of Object.values(data.techniques)) {
    const bucket = groups.get(t.tactic);
    if (bucket) bucket.push(t);
    else groups.set(t.tactic, [t]);
  }
  const sortedTactics = [...groups.keys()].sort((a, b) => a.localeCompare(b));

  return (
    <div className="min-h-screen bg-breach-bg p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="bg-breach-surface border border-breach-border rounded-xl p-6">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h1 className="text-xl font-black text-breach-text">Technique Dossier</h1>
              <p className="text-[10px] text-gray-600 mt-0.5">
                Every MITRE ATT&amp;CK technique you've encountered across your runs, with the real-world incident it's drawn from.
              </p>
            </div>
            <span className="text-xs font-bold px-2.5 py-1 rounded-full uppercase tracking-wider bg-yellow-500/10 text-yellow-500 border border-yellow-500/20">
              {data.encountered_count}/{data.total_techniques} entries
            </span>
          </div>
        </div>

        {sortedTactics.map((tactic) => (
          <TacticGroup key={tactic} tactic={tactic} techniques={groups.get(tactic)!} />
        ))}
      </div>
    </div>
  );
}
