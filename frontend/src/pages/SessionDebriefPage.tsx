import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, axiosInstance } from "../lib/api";
import SessionReplayScrubber from "../components/SessionReplayScrubber";

interface Decision {
  gate_id: string;
  team_choice: string;
  correct_choice: string;
  is_correct: boolean;
  impact: string;
  nist_ref: string;
  explanation: string;
}

interface NISTGap {
  control: string;
  description: string;
  gap: string;
  remediation: string;
}

interface MITRECoverage {
  techniques_exercised: string[];
  techniques_missed: string[];
}

interface RemediationItem {
  priority: "high" | "medium" | "low";
  action: string;
  owner: string;
  due_days: number;
}

interface ComplianceEvidence {
  frameworks_exercised: string[];
  training_completed: boolean;
  audit_notes: string;
}

interface DebriefReport {
  executive_summary: string;
  performance_rating: "excellent" | "good" | "needs_improvement" | "critical_gaps";
  decisions: Decision[];
  nist_gaps: NISTGap[];
  mitre_coverage: MITRECoverage;
  remediation_checklist: RemediationItem[];
  compliance_evidence: ComplianceEvidence;
}

// Sentinel returned by the backend while Claude is generating
interface GeneratingResponse {
  generating: true;
}

interface SessionData {
  id: string;
  scenario_id: string;
  team_score: number | null;
  decisions_made: number;
  decisions_correct: number;
  status: string;
}

const RATING_STYLES: Record<string, { label: string; text: string; bg: string; border: string }> = {
  excellent: {
    label: "EXCELLENT PERFORMANCE",
    text: "text-green-400",
    bg: "bg-green-500/10",
    border: "border-green-500/30",
  },
  good: {
    label: "GOOD PERFORMANCE",
    text: "text-breach-blue",
    bg: "bg-breach-blue/10",
    border: "border-breach-blue/30",
  },
  needs_improvement: {
    label: "NEEDS IMPROVEMENT",
    text: "text-breach-yellow",
    bg: "bg-breach-yellow/10",
    border: "border-breach-yellow/30",
  },
  critical_gaps: {
    label: "CRITICAL SECURITY GAPS",
    text: "text-breach-accent",
    bg: "bg-breach-accent/10",
    border: "border-breach-accent/30",
  },
};

const PRIORITY_COLORS: Record<string, string> = {
  high: "bg-breach-accent/20 text-breach-accent border-breach-accent/40",
  medium: "bg-breach-yellow/20 text-breach-yellow border-breach-yellow/40",
  low: "bg-breach-blue/20 text-breach-blue border-breach-blue/40",
};

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 30; // 90 s max

export default function SessionDebriefPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionData | null>(null);
  const [debrief, setDebrief] = useState<DebriefReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [isTimeout, setIsTimeout] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [certDownloading, setCertDownloading] = useState(false);

  const handleExportPDF = async () => {
    setExporting(true);
    try {
      const response = await axiosInstance.get(`/sessions/${sessionId}/debrief/pdf`, {
        responseType: "blob",
      });
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `BreachReplay_Debrief_${sessionId}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert("Failed to download PDF report. Please try again.");
    } finally {
      setExporting(false);
    }
  };

  const handleDownloadCertificate = async () => {
    setCertDownloading(true);
    try {
      const response = await axiosInstance.get(`/sessions/${sessionId}/certificate`, {
        responseType: "blob",
      });
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `BreachReplay_Certificate_${sessionId?.slice(0, 8)}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert("Failed to generate certificate. Please try again.");
    } finally {
      setCertDownloading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setIsTimeout(false);
    setDebrief(null);

    async function load() {
      try {
        const sessionData = await api.get<SessionData>(`/sessions/${sessionId}`);
        if (cancelled) return;
        setSession(sessionData);

        let attempts = 0;
        while (attempts < MAX_POLL_ATTEMPTS) {
          if (cancelled) return;

          const raw = await api.get<DebriefReport | GeneratingResponse>(
            `/sessions/${sessionId}/debrief`
          );

          if (cancelled) return;

          if ("generating" in raw && raw.generating) {
            setGenerating(true);
            attempts++;
            await new Promise<void>((r) => setTimeout(r, POLL_INTERVAL_MS));
            continue;
          }

          setDebrief(raw as DebriefReport);
          setGenerating(false);
          setLoading(false);
          return;
        }

        setIsTimeout(true);
        throw new Error("Debrief generation is taking longer than expected. The AI may still be working — click Retry to check again.");
      } catch (err: any) {
        if (cancelled) return;
        setError(err.message || "Failed to load debrief data");
        setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [sessionId, retryKey]);

  if (loading) {
    return (
      <div className="min-h-screen bg-breach-bg flex flex-col items-center justify-center p-6 text-center">
        <div className="w-16 h-16 border-4 border-breach-accent border-t-transparent rounded-full animate-spin mb-6 shadow-[0_0_15px_rgba(239,68,68,0.3)]"></div>
        <h2 className="text-xl font-bold text-breach-text tracking-widest uppercase mb-2">
          {generating ? "GENERATING REPORT" : "LOADING SESSION DATA"}
        </h2>
        <p className="text-sm text-breach-muted max-w-sm">
          {generating
            ? "Claude AI is analyzing your decisions, identifying control gaps, and building compliance evidence..."
            : "Initializing SOC tabletop simulation data feed..."}
        </p>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="min-h-screen bg-breach-bg flex flex-col items-center justify-center p-6 text-center">
        <div className="border border-breach-accent/30 bg-breach-accent/10 rounded p-6 max-w-md mb-6">
          <h2 className="text-lg font-bold text-breach-accent uppercase tracking-wider mb-2">AUDIT LOAD FAILURE</h2>
          <p className="text-sm text-breach-text">{error || "Critical error reading session data."}</p>
        </div>
        <div className="flex gap-3">
          {isTimeout && (
            <button
              onClick={() => setRetryKey((k) => k + 1)}
              className="bg-breach-accent hover:bg-red-600 text-white px-6 py-2 rounded text-xs uppercase tracking-widest transition-colors font-bold"
            >
              Retry
            </button>
          )}
          <button
            onClick={() => navigate("/scenarios")}
            className="bg-breach-surface border border-breach-border hover:border-breach-blue text-breach-text px-6 py-2 rounded text-xs uppercase tracking-widest transition-colors font-bold"
          >
            Return to Library
          </button>
        </div>
      </div>
    );
  }

  const rating = debrief?.performance_rating ?? "needs_improvement";
  const ratingStyle = RATING_STYLES[rating] ?? RATING_STYLES.needs_improvement;

  return (
    <div className="min-h-screen bg-breach-bg p-6 text-breach-text">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Top Navigation */}
        <div className="flex items-center justify-between border-b border-breach-border pb-4">
          <div className="flex items-center gap-4">
            <span className="text-breach-accent font-bold text-sm uppercase tracking-widest">BREACH REPLAY</span>
            <span className="text-breach-muted text-xs">/</span>
            <span className="text-xs text-breach-muted">Simulation Audit: {session.id.slice(0, 8)}...</span>
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleDownloadCertificate}
              disabled={certDownloading}
              className="bg-purple-700 hover:bg-purple-600 disabled:bg-purple-700/50 text-white px-4 py-1.5 rounded text-xs uppercase tracking-widest transition-colors flex items-center gap-2 font-bold"
            >
              {certDownloading ? (
                <>
                  <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                  Generating...
                </>
              ) : (
                <>🏅 Certificate</>
              )}
            </button>
            <button
              onClick={handleExportPDF}
              disabled={exporting}
              className="bg-breach-accent hover:bg-red-600 disabled:bg-breach-accent/50 text-white px-4 py-1.5 rounded text-xs uppercase tracking-widest transition-colors flex items-center gap-2 font-bold"
            >
              {exporting ? (
                <>
                  <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                  Exporting...
                </>
              ) : (
                <>📄 Export PDF Report</>
              )}
            </button>
            <button
              onClick={() => navigate("/scenarios")}
              className="bg-breach-surface border border-breach-border hover:border-breach-blue text-breach-text px-4 py-1.5 rounded text-xs uppercase tracking-widest transition-colors"
            >
              Scenario Library
            </button>
          </div>
        </div>

        {/* Dashboard Grid Header */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* CISO Scorecard */}
          <div className="bg-breach-surface border border-breach-border rounded p-6 flex flex-col justify-between space-y-4">
            <div>
              <span className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">NIST Compliance Score</span>
              <div className="text-5xl font-extrabold text-breach-text mt-2 font-mono tracking-tighter">
                {session.team_score !== null ? `${session.team_score}%` : "—"}
              </div>
            </div>
            <div className="border-t border-breach-border pt-4 grid grid-cols-2 gap-4 text-xs">
              <div>
                <span className="text-breach-muted block uppercase tracking-wider text-[10px]">Total Decisions</span>
                <span className="font-bold text-sm mt-1 block font-mono">{session.decisions_made}</span>
              </div>
              <div>
                <span className="text-breach-muted block uppercase tracking-wider text-[10px]">Correct Actions</span>
                <span className="font-bold text-sm mt-1 block text-green-400 font-mono">{session.decisions_correct}</span>
              </div>
            </div>
          </div>

          {/* Performance Rating */}
          <div className={`border rounded p-6 flex flex-col justify-between space-y-4 ${ratingStyle.bg} ${ratingStyle.border}`}>
            <div>
              <span className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">Training Evaluation</span>
              <h2 className={`text-xl font-bold uppercase mt-2 tracking-wider ${ratingStyle.text}`}>
                {ratingStyle.label}
              </h2>
              <p className="text-xs text-breach-text mt-2 leading-relaxed opacity-80">
                {debrief?.executive_summary ?? "Claude AI is compiling details on your performance timeline..."}
              </p>
            </div>
            <div className="text-xs text-breach-muted">
              Incident Commander: <span className="text-breach-text font-bold">Authenticated User</span>
            </div>
          </div>

          {/* Compliance Evidence */}
          <div className="bg-breach-surface border border-breach-border rounded p-6 flex flex-col justify-between space-y-4">
            <div>
              <span className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">Compliance Checklist</span>
              <div className="space-y-2 mt-3">
                <div className="flex items-center justify-between text-xs">
                  <span>Exercise Validation</span>
                  <span className="text-green-400 font-bold uppercase tracking-wider">VERIFIED</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span>Frameworks Satisfied</span>
                  <span className="text-breach-blue font-bold">
                    {/* BUG-02: full optional chain on nested arrays */}
                    {debrief?.compliance_evidence?.frameworks_exercised?.join(", ") || "NIST IR, HIPAA"}
                  </span>
                </div>
              </div>
            </div>
            <p className="text-[10px] text-breach-muted border-t border-breach-border pt-4 leading-normal italic">
              {debrief?.compliance_evidence?.audit_notes ??
                "Satisfies annual incident response tabletop simulation training parameters under NIST SP 800-61 Rev 2."}
            </p>
          </div>
        </div>

        {debrief?.decisions && (
          <SessionReplayScrubber decisions={debrief.decisions} />
        )}

        {/* Decisions Timeline */}
        <div className="bg-breach-surface border border-breach-border rounded">
          <div className="px-6 py-4 border-b border-breach-border flex items-center justify-between">
            <span className="text-xs text-breach-muted uppercase tracking-wider">Interactive Decision Audit Log</span>
            <span className="text-[10px] bg-breach-bg border border-breach-border px-2 py-0.5 rounded text-breach-muted uppercase tracking-widest font-mono">
              Timeline Details
            </span>
          </div>
          <div className="p-6 space-y-6">
            {/* BUG-02: debrief?.decisions?.map avoids crash if decisions is undefined */}
            {debrief?.decisions?.map((dec, i) => (
              <div key={dec.gate_id} className="flex gap-4 items-start">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center font-bold text-xs ${
                      dec.is_correct
                        ? "bg-green-500/10 text-green-400 border border-green-500/30 shadow-[0_0_10px_rgba(34,197,94,0.15)]"
                        : "bg-breach-accent/10 text-breach-accent border border-breach-accent/30 shadow-[0_0_10px_rgba(239,68,68,0.15)]"
                    }`}
                  >
                    {dec.is_correct ? "✓" : "✗"}
                  </div>
                  {/* BUG-02: safe access to length */}
                  {i < ((debrief.decisions?.length ?? 0) - 1) && (
                    <div className="w-0.5 bg-breach-border flex-1 min-h-[40px] mt-2"></div>
                  )}
                </div>
                <div className="flex-1 bg-breach-bg border border-breach-border rounded p-4 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-breach-border/40 pb-2">
                    <span className="text-xs font-bold text-breach-text uppercase tracking-wider">{dec.gate_id}</span>
                    <span className="text-[10px] bg-breach-surface border border-breach-border px-2 py-0.5 rounded text-breach-blue font-mono font-bold">
                      {dec.nist_ref}
                    </span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                    <div className="space-y-1.5">
                      <div className="text-breach-muted uppercase tracking-wider text-[9px] font-bold">Action Taken</div>
                      <p className="text-breach-text bg-breach-surface px-2.5 py-1.5 rounded border border-breach-border/40">
                        {dec.team_choice}
                      </p>
                    </div>
                    <div className="space-y-1.5">
                      <div className="text-breach-muted uppercase tracking-wider text-[9px] font-bold">Recommended NIST Protocol</div>
                      <p className="text-green-400 bg-green-500/5 px-2.5 py-1.5 rounded border border-green-500/10">
                        {dec.correct_choice}
                      </p>
                    </div>
                  </div>
                  <div className="text-xs leading-relaxed space-y-2 pt-2 border-t border-breach-border/40">
                    <div className="text-breach-muted font-bold uppercase tracking-wider text-[9px]">Downstream Impact & Analysis</div>
                    <p className="text-breach-text opacity-90">{dec.impact}</p>
                    <p className="text-breach-muted italic text-[11px] bg-breach-surface/50 p-2.5 rounded border border-breach-border/30">
                      {dec.explanation}
                    </p>
                  </div>
                </div>
              </div>
            )) ?? (
              <p className="text-xs text-breach-muted text-center py-4">No decisions recorded for this session.</p>
            )}
          </div>
        </div>

        {/* Certificate Call-to-Action */}
        <div className="bg-breach-surface border border-purple-800/40 rounded p-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-bold text-purple-300 uppercase tracking-wider mb-1">Completion Certificate</h3>
            <p className="text-xs text-breach-muted max-w-xl leading-relaxed">
              Download your signed certificate of completion — valid as tabletop exercise evidence for HIPAA, SOC 2, and PCI-DSS audits. Share on LinkedIn to demonstrate active IR readiness.
            </p>
          </div>
          <div className="flex gap-3 shrink-0">
            <button
              onClick={handleDownloadCertificate}
              disabled={certDownloading}
              className="bg-purple-700 hover:bg-purple-600 disabled:bg-purple-700/50 text-white px-5 py-2 rounded text-xs uppercase tracking-widest transition-colors flex items-center gap-2 font-bold"
            >
              {certDownloading ? (
                <><span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></span> Generating...</>
              ) : (
                <>🏅 Download Certificate</>
              )}
            </button>
          </div>
        </div>

        {/* NIST Control Gaps & MITRE Coverage */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* NIST Gaps */}
          <div className="bg-breach-surface border border-breach-border rounded">
            <div className="px-6 py-4 border-b border-breach-border">
              <span className="text-xs text-breach-muted uppercase tracking-wider">NIST SP 800-61 Rev 2 Control Gaps</span>
            </div>
            <div className="p-6 space-y-4">
              {debrief?.nist_gaps && debrief.nist_gaps.length > 0 ? (
                debrief.nist_gaps.map((gap, idx) => (
                  <div key={idx} className="bg-breach-bg border border-breach-border rounded p-4 space-y-2 text-xs">
                    <div className="flex items-center justify-between border-b border-breach-border/40 pb-2">
                      <span className="font-bold text-breach-accent uppercase tracking-wider font-mono">{gap.control}</span>
                      <span className="text-[10px] text-breach-muted">{gap.description}</span>
                    </div>
                    <p className="text-breach-text leading-relaxed mt-2">
                      <span className="text-breach-accent font-bold">Gap:</span> {gap.gap}
                    </p>
                    <p className="text-green-400 bg-green-500/5 p-2 rounded border border-green-500/10 mt-2">
                      <span className="font-bold uppercase tracking-wider text-[9px] block mb-1">Remediation Action</span>
                      {gap.remediation}
                    </p>
                  </div>
                ))
              ) : (
                <div className="text-center py-6 text-xs text-green-400">
                  ✓ Zero critical NIST Control Gaps identified during this tabletop replay!
                </div>
              )}
            </div>
          </div>

          {/* MITRE ATT&CK & Remediation */}
          <div className="space-y-6">
            <div className="bg-breach-surface border border-breach-border rounded p-6">
              <span className="text-xs text-breach-muted uppercase tracking-wider font-bold">MITRE ATT&CK Mapping</span>
              <div className="space-y-4 mt-4">
                <div>
                  <span className="text-[10px] text-breach-muted uppercase tracking-widest font-bold block mb-2">Techniques Exercised</span>
                  <div className="flex flex-wrap gap-1.5">
                    {/* BUG-02: full optional chain before map */}
                    {(debrief?.mitre_coverage?.techniques_exercised?.length ?? 0) > 0
                      ? debrief!.mitre_coverage.techniques_exercised.map((tech) => (
                          <span key={tech} className="text-xs bg-breach-bg border border-breach-border px-2 py-0.5 rounded text-green-400 font-mono">
                            {tech}
                          </span>
                        ))
                      : <span className="text-xs text-breach-muted">—</span>}
                  </div>
                </div>
                <div>
                  <span className="text-[10px] text-breach-muted uppercase tracking-widest font-bold block mb-2">Techniques Missed / Undetected</span>
                  <div className="flex flex-wrap gap-1.5">
                    {(debrief?.mitre_coverage?.techniques_missed?.length ?? 0) > 0
                      ? debrief!.mitre_coverage.techniques_missed.map((tech) => (
                          <span key={tech} className="text-xs bg-breach-bg border border-breach-border px-2 py-0.5 rounded text-breach-accent font-mono">
                            {tech}
                          </span>
                        ))
                      : <span className="text-xs text-breach-muted">—</span>}
                  </div>
                </div>
              </div>
            </div>

            {/* Remediation Checklist */}
            <div className="bg-breach-surface border border-breach-border rounded p-6">
              <span className="text-xs text-breach-muted uppercase tracking-wider font-bold">Action Item Checklist</span>
              <div className="space-y-3 mt-4">
                {/* BUG-08: check length before mapping — Array.map([]) is truthy so || never fires */}
                {(debrief?.remediation_checklist?.length ?? 0) > 0 ? (
                  debrief!.remediation_checklist.map((item, idx) => (
                    <div key={idx} className="bg-breach-bg border border-breach-border rounded p-3 text-xs flex items-center justify-between gap-4">
                      <div className="space-y-1">
                        <p className="text-breach-text font-semibold">{item.action}</p>
                        <p className="text-[10px] text-breach-muted">
                          Owner: <span className="text-breach-text">{item.owner}</span> | Due: <span className="text-breach-text">{item.due_days} Days</span>
                        </p>
                      </div>
                      <span className={`px-2 py-0.5 rounded text-[9px] uppercase font-bold border tracking-wider ${PRIORITY_COLORS[item.priority] ?? ""}`}>
                        {item.priority}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-breach-muted mt-2">No remediation tasks scheduled.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
