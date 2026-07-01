import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";

// Optional, dismissible "why was that the right call?" knowledge-check panel.
// Triggered after a gate's consequence reveal — never blocks progression. If the
// player ignores/dismisses it, the underlying gameplay (gate flow) is unaffected.

interface KnowledgeCheckQuestion {
  id: string;
  scenario_id: string | null;
  technique_id: string | null;
  nist_control_ref: string | null;
  question: string;
  options: string[];
}

interface AttemptResult {
  is_correct: boolean;
  correct_index: number;
  explanation: string;
}

export default function KnowledgeCheckModal({ onDismiss }: { onDismiss: () => void }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [result, setResult] = useState<AttemptResult | null>(null);

  const { data: check, isLoading, isError } = useQuery<KnowledgeCheckQuestion>({
    queryKey: ["knowledge-check-next"],
    queryFn: () => axiosInstance.get("/learning/knowledge-check/next").then((r) => r.data),
    retry: false,
  });

  const attemptMutation = useMutation({
    mutationFn: (chosen_index: number) =>
      axiosInstance
        .post(`/learning/knowledge-check/${check!.id}/attempt`, { chosen_index })
        .then((r) => r.data as AttemptResult),
    onSuccess: (data) => setResult(data),
  });

  const handleSelect = (idx: number) => {
    if (result || attemptMutation.isPending) return;
    setSelected(idx);
    attemptMutation.mutate(idx);
  };

  if (isError) return null;

  return (
    <div className="fixed inset-0 z-[90] bg-black/70 flex items-center justify-center px-4">
      <div className="w-full max-w-md border border-cyan-800/50 bg-slate-950 rounded-xl shadow-2xl overflow-hidden font-mono">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/70">
          <span className="text-[10px] text-cyan-400 uppercase tracking-widest font-bold">
            💡 Why was that the right call?
          </span>
          <button
            onClick={onDismiss}
            className="text-slate-500 hover:text-slate-300 text-xs px-2"
            aria-label="Dismiss knowledge check"
          >
            ✕ skip
          </button>
        </div>

        <div className="p-4 space-y-3">
          {isLoading && (
            <p className="text-xs text-slate-500">Loading a quick knowledge check...</p>
          )}

          {check && !result && (
            <>
              <p className="text-sm text-slate-300 leading-relaxed">{check.question}</p>
              <div className="space-y-2">
                {check.options.map((opt, i) => (
                  <button
                    key={i}
                    onClick={() => handleSelect(i)}
                    disabled={attemptMutation.isPending}
                    className={`w-full text-left px-3 py-2 rounded-lg border text-xs transition-colors ${
                      selected === i
                        ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-200"
                        : "border-slate-700 hover:border-cyan-600/50 hover:bg-cyan-500/5 text-slate-300"
                    }`}
                  >
                    <span className="inline-block w-5 h-5 rounded-full border border-slate-600 text-center text-[10px] leading-5 mr-2 font-bold">
                      {String.fromCharCode(65 + i)}
                    </span>
                    {opt}
                  </button>
                ))}
              </div>
            </>
          )}

          {check && result && (
            <div
              className={`rounded-lg p-3 border ${
                result.is_correct
                  ? "border-green-700/50 bg-green-950/30"
                  : "border-red-700/50 bg-red-950/30"
              }`}
            >
              <p
                className={`text-xs font-bold uppercase tracking-widest mb-2 ${
                  result.is_correct ? "text-green-400" : "text-red-400"
                }`}
              >
                {result.is_correct ? "✓ Correct" : "✗ Not quite"}
              </p>
              <p className="text-xs text-slate-300 leading-relaxed">{result.explanation}</p>
              <button
                onClick={onDismiss}
                className="mt-3 w-full py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-black text-xs font-bold uppercase tracking-widest transition-colors"
              >
                Continue
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
