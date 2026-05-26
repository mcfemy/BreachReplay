import { useState } from "react";
import { api } from "../lib/api";

interface AlertObject {
  timestamp: string;
  severity: "critical" | "high" | "medium" | "low";
  source_system: string;
  rule_id: string;
  description: string;
  raw_log?: string;
}

interface DecisionOption {
  text: string;
  consequence_if_chosen: string;
}

interface DecisionGate {
  id: string;
  trigger_timestamp: string;
  context_summary: string;
  options: DecisionOption[];
  correct_index: number;
  consequence_if_wrong: string;
  rationale: string;
  nist_control_ref: string;
  mitre_technique: string;
}

interface Scenario {
  id: string;
  title: string;
  description: string | null;
  industry_vertical: string | null;
  difficulty: string;
  estimated_minutes: number;
  initial_access_vector: string | null;
  alert_sequence?: AlertObject[];
  decision_tree?: DecisionGate[];
}

interface ScenarioReviewModalProps {
  scenario: Scenario;
  onClose: () => void;
  onApproved: () => void;
}

export default function ScenarioReviewModal({ scenario, onClose, onApproved }: ScenarioReviewModalProps) {
  const [title, setTitle] = useState(scenario.title);
  const [description, setDescription] = useState(scenario.description || "");
  const [accessVector, setAccessVector] = useState(scenario.initial_access_vector || "");
  const [industry, setIndustry] = useState(scenario.industry_vertical || "other");
  const [minutes, setMinutes] = useState(scenario.estimated_minutes);
  const [alerts, setAlerts] = useState<AlertObject[]>(scenario.alert_sequence || []);
  const [gates, setGates] = useState<DecisionGate[]>(scenario.decision_tree || []);
  
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleAlertChange = (index: number, field: keyof AlertObject, value: string) => {
    const updated = [...alerts];
    updated[index] = { ...updated[index], [field]: value };
    setAlerts(updated);
  };

  const handleGateChange = (index: number, field: keyof DecisionGate, value: any) => {
    const updated = [...gates];
    updated[index] = { ...updated[index], [field]: value };
    setGates(updated);
  };

  async function handleApprove() {
    setSubmitting(true);
    setError("");
    try {
      // 1. Update scenario contents (via a patch or approval update)
      // Since scenarios might have been updated, we patch/update the status first
      await api.patch(`/scenarios/${scenario.id}/approve`, {
        title,
        description,
        initial_access_vector: accessVector,
        industry_vertical: industry,
        estimated_minutes: minutes,
        alert_sequence: alerts,
        decision_tree: gates,
      });
      onApproved();
    } catch (err: any) {
      setError(err.message || "Failed to approve scenario");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReject() {
    setSubmitting(true);
    setError("");
    try {
      await api.patch(`/scenarios/${scenario.id}/reject`, {});
      onApproved(); // Reload scenario list
    } catch (err: any) {
      setError(err.message || "Failed to reject scenario");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/85 flex items-center justify-center p-6 z-50 overflow-y-auto">
      <div className="bg-breach-surface border border-breach-border rounded-lg max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden shadow-[0_0_50px_rgba(0,0,0,0.8)]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-breach-border flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-breach-accent uppercase tracking-widest">Scenario Extraction Review</h2>
            <p className="text-[10px] text-breach-muted mt-1">Review and sanitize Claude's extracted timeline before publishing.</p>
          </div>
          <button onClick={onClose} className="text-breach-muted hover:text-breach-text text-sm font-bold">✕ Close</button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto space-y-6 text-xs">
          {error && (
            <div className="bg-breach-accent/15 border border-breach-accent/30 text-breach-accent p-3 rounded font-mono">
              [CRITICAL ERROR]: {error}
            </div>
          )}

          {/* Section 1: Metadata */}
          <div className="bg-breach-bg border border-breach-border/60 rounded p-4 space-y-4">
            <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider border-b border-breach-border/40 pb-2">
              1. General Details
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-[10px] text-breach-muted uppercase font-semibold">Scenario Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded focus:outline-none focus:border-breach-blue"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-breach-muted uppercase font-semibold">Initial Access Vector</label>
                <input
                  value={accessVector}
                  onChange={(e) => setAccessVector(e.target.value)}
                  className="w-full bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded focus:outline-none focus:border-breach-blue"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-breach-muted uppercase font-semibold">Industry Vertical</label>
                <select
                  value={industry}
                  onChange={(e) => setIndustry(e.target.value)}
                  className="w-full bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded focus:outline-none focus:border-breach-blue"
                >
                  <option value="healthcare">Healthcare</option>
                  <option value="energy">Energy</option>
                  <option value="finance">Finance</option>
                  <option value="government">Government</option>
                  <option value="technology">Technology</option>
                  <option value="retail">Retail</option>
                  <option value="education">Education</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-breach-muted uppercase font-semibold">Estimated Time (Minutes)</label>
                <input
                  type="number"
                  value={minutes}
                  onChange={(e) => setMinutes(parseInt(e.target.value) || 0)}
                  className="w-full bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded focus:outline-none focus:border-breach-blue"
                />
              </div>
            </div>
            <div className="space-y-1 pt-2">
              <label className="text-[10px] text-breach-muted uppercase font-semibold">Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="w-full bg-breach-surface border border-breach-border text-breach-text px-3 py-2 rounded focus:outline-none focus:border-breach-blue"
              />
            </div>
          </div>

          {/* Section 2: Alert Feed logs */}
          <div className="bg-breach-bg border border-breach-border/60 rounded p-4 space-y-4">
            <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider border-b border-breach-border/40 pb-2">
              2. Extracted Alert Sequence ({alerts.length} Events)
            </h3>
            <div className="space-y-4 max-h-[300px] overflow-y-auto pr-2">
              {alerts.map((alert, idx) => (
                <div key={idx} className="border border-breach-border/40 bg-breach-surface rounded p-3 grid grid-cols-1 md:grid-cols-4 gap-3">
                  <div className="space-y-1">
                    <label className="text-[9px] text-breach-muted uppercase font-semibold">Timestamp</label>
                    <input
                      value={alert.timestamp}
                      onChange={(e) => handleAlertChange(idx, "timestamp", e.target.value)}
                      className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[9px] text-breach-muted uppercase font-semibold">Severity</label>
                    <select
                      value={alert.severity}
                      onChange={(e) => handleAlertChange(idx, "severity", e.target.value as any)}
                      className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                    >
                      <option value="critical">Critical</option>
                      <option value="high">High</option>
                      <option value="medium">Medium</option>
                      <option value="low">Low</option>
                    </select>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[9px] text-breach-muted uppercase font-semibold">Source</label>
                    <input
                      value={alert.source_system}
                      onChange={(e) => handleAlertChange(idx, "source_system", e.target.value)}
                      className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[9px] text-breach-muted uppercase font-semibold">Rule ID</label>
                    <input
                      value={alert.rule_id}
                      onChange={(e) => handleAlertChange(idx, "rule_id", e.target.value)}
                      className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                    />
                  </div>
                  <div className="md:col-span-4 space-y-1">
                    <label className="text-[9px] text-breach-muted uppercase font-semibold">Alert Message Description</label>
                    <input
                      value={alert.description}
                      onChange={(e) => handleAlertChange(idx, "description", e.target.value)}
                      className="w-full bg-breach-bg border border-breach-border text-breach-text px-2.5 py-1.5 rounded focus:outline-none"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Section 3: Decision Gates */}
          <div className="bg-breach-bg border border-breach-border/60 rounded p-4 space-y-4">
            <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider border-b border-breach-border/40 pb-2">
              3. Extracted Decision Gates ({gates.length} active gates)
            </h3>
            <div className="space-y-4 max-h-[300px] overflow-y-auto pr-2">
              {gates.map((gate, idx) => (
                <div key={idx} className="border border-breach-border/40 bg-breach-surface rounded p-3 space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                    <div className="space-y-1">
                      <label className="text-[9px] text-breach-muted uppercase font-semibold">Gate ID</label>
                      <input
                        value={gate.id}
                        onChange={(e) => handleGateChange(idx, "id", e.target.value)}
                        className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[9px] text-breach-muted uppercase font-semibold">Trigger Offset</label>
                      <input
                        value={gate.trigger_timestamp}
                        onChange={(e) => handleGateChange(idx, "trigger_timestamp", e.target.value)}
                        className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[9px] text-breach-muted uppercase font-semibold">NIST Control</label>
                      <input
                        value={gate.nist_control_ref}
                        onChange={(e) => handleGateChange(idx, "nist_control_ref", e.target.value)}
                        className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[9px] text-breach-muted uppercase font-semibold">MITRE Technique</label>
                      <input
                        value={gate.mitre_technique}
                        onChange={(e) => handleGateChange(idx, "mitre_technique", e.target.value)}
                        className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1 rounded focus:outline-none"
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[9px] text-breach-muted uppercase font-semibold">Context Summary (Tabletop Prompt)</label>
                    <textarea
                      value={gate.context_summary}
                      onChange={(e) => handleGateChange(idx, "context_summary", e.target.value)}
                      rows={2}
                      className="w-full bg-breach-bg border border-breach-border text-breach-text px-2.5 py-1.5 rounded focus:outline-none"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-breach-border bg-breach-surface/50 flex items-center justify-between">
          <button
            onClick={handleReject}
            disabled={submitting}
            className="bg-breach-bg border border-breach-border hover:border-breach-accent hover:text-breach-accent text-breach-muted px-4 py-2 rounded text-xs uppercase tracking-widest font-bold transition-colors disabled:opacity-50"
          >
            {submitting ? "Processing..." : "Reject Ingestion"}
          </button>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="bg-breach-bg border border-breach-border hover:border-breach-blue text-breach-text px-4 py-2 rounded text-xs uppercase tracking-widest font-bold transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleApprove}
              disabled={submitting}
              className="bg-green-500 hover:bg-green-600 text-black px-6 py-2 rounded text-xs uppercase tracking-widest font-bold transition-colors disabled:opacity-50 shadow-[0_0_15px_rgba(34,197,94,0.3)]"
            >
              {submitting ? "Approve..." : "Approve & Publish"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
