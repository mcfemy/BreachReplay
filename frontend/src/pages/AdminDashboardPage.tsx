import { useEffect, useState, useRef } from "react";
import { api, API_BASE } from "../lib/api";
import ScenarioReviewModal from "../components/ScenarioReviewModal";

interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface BreachDocument {
  id: string;
  filename: string;
  status: "processing" | "completed" | "failed";
  created_at: string;
}

interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  ip_address: string | null;
  user_agent: string | null;
  details: any;
  created_at: string;
}

interface Scenario {
  id: string;
  title: string;
  description: string | null;
  difficulty: string;
  status: string;
  estimated_minutes: number;
  industry_vertical: string | null;
  initial_access_vector: string | null;
  alert_sequence?: any[];
  decision_tree?: any[];
}

interface ScenarioCoverage {
  id: string;
  title: string;
  industry: string | null;
  difficulty: string;
  mitre_techniques: string[];
  nist_controls: string[];
  frameworks: string[];
}

interface AnalystPerformance {
  user_id: string;
  full_name: string;
  email: string;
  role: string;
  sessions_completed: number;
  average_score: number;
  decisions_made: number;
  decisions_correct: number;
  accuracy_rate: number;
}

interface Calibration {
  scenario_id: string;
  title: string;
  designed_difficulty: string;
  play_count: number;
  avg_score: number | null;
  calibrated_difficulty: string;
  is_calibrated: boolean;
}

interface EvidenceLog {
  session_id: string;
  scenario_title: string;
  completed_at: string;
  score: number | null;
  participant_count: number;
  frameworks: string[];
  audit_notes: string;
}

interface PrivateScenario {
  id: string;
  title: string;
  industry: string | null;
  difficulty: string;
  play_count: number;
  avg_score: number | null;
  last_played_at: string | null;
  mitre_techniques: string[];
  nist_controls: string[];
  source_reference: string | null;
  version?: number;
  version_history?: any[];
}

interface ReadinessTrend {
  week: string;
  sessions: number;
  avg_score: number | null;
}

interface Recommendation {
  id: string;
  title: string;
  difficulty: string;
  industry: string | null;
  estimated_minutes: number;
  new_nist_controls: string[];
  new_mitre_techniques: string[];
  gap_coverage: number;
}

interface ComplianceAnalytics {
  organization_name: string;
  organization_tier: string;
  custom_docs_count: number;
  custom_docs_limit: number;
  readiness_score: number;
  readiness_components: { session_frequency: number; avg_score: number; nist_coverage: number; proprietary_library: number };
  readiness_trend: ReadinessTrend[];
  recommendations: Recommendation[];
  scenario_coverage: ScenarioCoverage[];
  analyst_performance: AnalystPerformance[];
  calibrations: Calibration[];
  compliance_evidence: EvidenceLog[];
  private_scenarios: PrivateScenario[];
}


export default function AdminDashboardPage() {
  const [activeTab, setActiveTab] = useState<"users" | "ingest" | "review" | "audit" | "compliance">("users");
  
  // States
  const [users, setUsers] = useState<User[]>([]);
  const [documents, setDocuments] = useState<BreachDocument[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  
  // Ingestion File Upload
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Review Modal State
  const [reviewScenario, setReviewScenario] = useState<Scenario | null>(null);

  // Compliance Analytics State
  const [complianceData, setComplianceData] = useState<ComplianceAnalytics | null>(null);
  const [exportingCSV, setExportingCSV] = useState(false);
  const [expandedVersionId, setExpandedVersionId] = useState<string | null>(null);

  // Pipeline controls
  const [triggeringPipeline, setTriggeringPipeline] = useState(false);
  const [pipelineMessage, setPipelineMessage] = useState("");
  const [approvingAll, setApprovingAll] = useState(false);

  useEffect(() => {
    loadTabData();
  }, [activeTab]);

  async function handleSnapshotVersion(scenarioId: string) {
    try {
      await api.post(`/admin/scenarios/${scenarioId}/version`, {});
      const data = await api.get<ComplianceAnalytics>("/admin/compliance-analytics");
      setComplianceData(data);
    } catch (err: any) {
      alert(err.message || "Failed to snapshot version");
    }
  }

  async function handleExportCSV() {
    setExportingCSV(true);
    try {
      const token = localStorage.getItem("br_token");
      const res = await fetch(`${API_BASE}/admin/compliance-evidence/export`, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) throw new Error("CSV Export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "BreachReplay_Compliance_Evidence.csv");
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(err.message || "Failed to export compliance CSV");
    } finally {
      setExportingCSV(false);
    }
  }

  async function loadTabData() {
    setLoading(true);
    setError("");
    try {
      if (activeTab === "users") {
        const data = await api.get<User[]>("/admin/users");
        setUsers(data);
      } else if (activeTab === "ingest") {
        try {
          const data = await api.get<BreachDocument[]>("/scenarios/documents");
          setDocuments(data);
        } catch {
          setDocuments([]);
        }
      } else if (activeTab === "review") {
        const data = await api.get<Scenario[]>("/admin/scenarios/pending");
        setScenarios(data);
      } else if (activeTab === "audit") {
        const data = await api.get<AuditLog[]>("/admin/audit-logs");
        setAuditLogs(data);
      } else if (activeTab === "compliance") {
        const data = await api.get<ComplianceAnalytics>("/admin/compliance-analytics");
        setComplianceData(data);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load admin panel data");
    } finally {
      setLoading(false);
    }
  }

  // --- User Management Actions ---
  async function handleToggleActive(userId: string) {
    try {
      const updated = await api.patch<User>(`/admin/users/${userId}/toggle-active`);
      setUsers(users.map((u) => (u.id === userId ? updated : u)));
    } catch (err: any) {
      alert(err.message || "Failed to toggle active status");
    }
  }

  async function handleRoleChange(userId: string, newRole: string) {
    try {
      const updated = await api.patch<User>(`/admin/users/${userId}/role`, { role: newRole });
      setUsers(users.map((u) => (u.id === userId ? updated : u)));
    } catch (err: any) {
      alert(err.message || "Failed to update role");
    }
  }

  // --- Document Ingestion Upload Actions ---
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await uploadFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      await uploadFile(e.target.files[0]);
    }
  };

  async function uploadFile(file: File) {
    setUploading(true);
    setUploadError("");
    const formData = new FormData();
    formData.append("file", file);

    try {
      // Direct raw fetch/post is used since we are uploading multipart FormData
      const token = localStorage.getItem("br_token");
      const res = await fetch(`${API_BASE}/scenarios/upload-document`, {
        method: "POST",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Upload failed");
      }

      const doc = await res.json();
      setDocuments((prev) => [
        { id: doc.id, filename: doc.filename, status: doc.status, created_at: doc.created_at },
        ...prev,
      ]);
      alert("Breach Document successfully uploaded! Claude scenario extraction task queued.");
      loadTabData(); // Reload tab
    } catch (err: any) {
      setUploadError(err.message || "File upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleTriggerPipeline() {
    setTriggeringPipeline(true);
    setPipelineMessage("");
    try {
      const result = await api.post<{ triggered_at: string; message: string }>("/admin/pipeline/trigger", {});
      setPipelineMessage(result.message);
    } catch (err: any) {
      setPipelineMessage(err.message || "Failed to trigger pipeline");
    } finally {
      setTriggeringPipeline(false);
    }
  }

  async function handleApproveAll() {
    setApprovingAll(true);
    try {
      await Promise.all(scenarios.map((s) => api.post(`/admin/scenarios/${s.id}/approve`, {})));
      await loadTabData();
    } catch (err: any) {
      alert(err.message || "Failed to approve all");
    } finally {
      setApprovingAll(false);
    }
  }

  return (
    <div className="min-h-screen bg-breach-bg text-breach-text p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Top Header */}
        <div className="border-b border-breach-border pb-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold uppercase tracking-widest text-breach-text">Admin Dashboard</h1>
            <p className="text-breach-muted text-xs mt-1">Tenant Workspace and Ingestion Console</p>
          </div>
        </div>

        {/* Tab switcher */}
        <div className="flex border-b border-breach-border/60 text-xs">
          <button
            onClick={() => setActiveTab("users")}
            className={`px-6 py-2.5 font-bold uppercase tracking-wider transition-colors border-b-2 ${
              activeTab === "users" ? "border-breach-blue text-breach-blue" : "border-transparent text-breach-muted hover:text-breach-text"
            }`}
          >
            User Management
          </button>
          <button
            onClick={() => setActiveTab("ingest")}
            className={`px-6 py-2.5 font-bold uppercase tracking-wider transition-colors border-b-2 ${
              activeTab === "ingest" ? "border-breach-blue text-breach-blue" : "border-transparent text-breach-muted hover:text-breach-text"
            }`}
          >
            Disclosures Ingestion
          </button>
          <button
            onClick={() => setActiveTab("review")}
            className={`px-6 py-2.5 font-bold uppercase tracking-wider transition-colors border-b-2 ${
              activeTab === "review" ? "border-breach-blue text-breach-blue" : "border-transparent text-breach-muted hover:text-breach-text"
            }`}
          >
            Scenarios Review Center
          </button>
          <button
            onClick={() => setActiveTab("audit")}
            className={`px-6 py-2.5 font-bold uppercase tracking-wider transition-colors border-b-2 ${
              activeTab === "audit" ? "border-breach-blue text-breach-blue" : "border-transparent text-breach-muted hover:text-breach-text"
            }`}
          >
            System Audit Logs
          </button>
          <button
            onClick={() => setActiveTab("compliance")}
            className={`px-6 py-2.5 font-bold uppercase tracking-wider transition-colors border-b-2 ${
              activeTab === "compliance" ? "border-breach-blue text-breach-blue" : "border-transparent text-breach-muted hover:text-breach-text"
            }`}
          >
            Compliance & Analytics
          </button>
        </div>

        {/* Tab Panels */}
        {loading ? (
          <div className="text-breach-muted text-xs font-mono py-12 text-center animate-pulse">
            RETRIEVING SECURITY WORKSPACE DATA...
          </div>
        ) : error ? (
          <div className="bg-breach-accent/10 border border-breach-accent/30 text-breach-accent p-4 rounded text-xs font-mono">
            [CRITICAL ERROR]: {error}
          </div>
        ) : (
          <div className="space-y-6">
            {/* PANEL 1: USER MANAGEMENT */}
            {activeTab === "users" && (
              <div className="bg-breach-surface border border-breach-border rounded overflow-hidden">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-breach-bg border-b border-breach-border uppercase text-[10px] text-breach-muted tracking-widest font-bold font-mono">
                      <th className="px-6 py-3.5">Name</th>
                      <th className="px-6 py-3.5">Email</th>
                      <th className="px-6 py-3.5">Assigned Role</th>
                      <th className="px-6 py-3.5">Status</th>
                      <th className="px-6 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-breach-border/60">
                    {users.map((user) => (
                      <tr key={user.id} className="hover:bg-breach-bg/30">
                        <td className="px-6 py-4 font-semibold text-breach-text">{user.full_name || "—"}</td>
                        <td className="px-6 py-4 font-mono text-breach-muted">{user.email}</td>
                        <td className="px-6 py-4">
                          <select
                            value={user.role}
                            onChange={(e) => handleRoleChange(user.id, e.target.value)}
                            className="bg-breach-bg border border-breach-border rounded text-breach-text text-xs px-2 py-1 focus:outline-none"
                          >
                            <option value="analyst">Analyst</option>
                            <option value="admin">Admin</option>
                            <option value="ciso">CISO</option>
                            <option value="observer">Observer</option>
                          </select>
                        </td>
                        <td className="px-6 py-4">
                          <span className={`font-mono text-[10px] uppercase font-bold ${user.is_active ? "text-green-400" : "text-breach-accent"}`}>
                            {user.is_active ? "[ACTIVE]" : "[DEACTIVATED]"}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <button
                            onClick={() => handleToggleActive(user.id)}
                            className={`px-3 py-1 rounded text-[10px] uppercase tracking-wider font-bold transition-colors ${
                              user.is_active
                                ? "bg-breach-accent/10 border border-breach-accent/30 text-breach-accent hover:bg-breach-accent/20"
                                : "bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20"
                            }`}
                          >
                            {user.is_active ? "Deactivate" : "Activate"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* PANEL 2: DISCLOSURES INGESTION */}
            {activeTab === "ingest" && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Upload drag drop */}
                <div className="lg:col-span-2 space-y-6">
                  <div
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                    className="border-2 border-dashed border-breach-border hover:border-breach-blue bg-breach-surface rounded-lg p-10 flex flex-col items-center justify-center text-center cursor-pointer transition-colors relative"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <input
                      type="file"
                      ref={fileInputRef}
                      onChange={handleFileSelect}
                      accept=".pdf,.txt,.docx"
                      className="hidden"
                    />
                    <div className="w-12 h-12 bg-breach-bg border border-breach-border rounded-full flex items-center justify-center text-lg text-breach-muted mb-4">
                      📥
                    </div>
                    <span className="text-xs font-bold text-breach-text uppercase tracking-wider mb-2">
                      Drag & Drop Breach Disclosure File
                    </span>
                    <p className="text-[10px] text-breach-muted max-w-xs leading-normal mb-4">
                      Accepts cybersecurity advisories in **PDF**, plain-text **TXT**, or **DOCX** formats (Max 20MB).
                    </p>
                    <button className="bg-breach-blue hover:bg-blue-600 text-black px-4 py-1.5 rounded text-[10px] uppercase tracking-widest font-bold transition-colors">
                      Select File
                    </button>
                    {uploading && (
                      <div className="absolute inset-0 bg-black/60 rounded-lg flex items-center justify-center">
                        <div className="w-8 h-8 border-2 border-breach-blue border-t-transparent rounded-full animate-spin"></div>
                      </div>
                    )}
                  </div>
                  {uploadError && (
                    <div className="bg-breach-accent/15 border border-breach-accent/30 text-breach-accent p-3 rounded text-[10px] font-mono">
                      [UPLOAD ERROR]: {uploadError}
                    </div>
                  )}
                </div>

                {/* Uploaded files history */}
                <div className="bg-breach-surface border border-breach-border rounded p-6 space-y-4">
                  <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider border-b border-breach-border pb-2">
                    Ingested Document Registry
                  </h3>
                  <div className="space-y-3 max-h-[400px] overflow-y-auto pr-1">
                    {documents.length > 0 ? (
                      documents.map((doc) => (
                        <div key={doc.id} className="bg-breach-bg border border-breach-border/60 rounded p-3 text-xs space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-breach-text truncate max-w-[150px]">{doc.filename}</span>
                            <span className={`font-mono text-[9px] uppercase font-bold ${
                              doc.status === "completed" ? "text-green-400" : doc.status === "failed" ? "text-breach-accent" : "text-breach-blue animate-pulse"
                            }`}>
                              [{doc.status}]
                            </span>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-[10px] text-breach-muted leading-relaxed">
                        No custom breach documents uploaded in this organization yet. Ingest a CISA PDF to build custom scenarios.
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* PANEL 3: SCENARIOS REVIEW CENTER */}
            {activeTab === "review" && (
              <div className="space-y-4">
                {/* Pipeline controls */}
                <div className="flex items-center gap-3 flex-wrap">
                  <button
                    onClick={handleTriggerPipeline}
                    disabled={triggeringPipeline}
                    className="bg-breach-blue hover:bg-blue-600 disabled:opacity-50 text-black px-4 py-2 rounded text-xs uppercase tracking-widest font-bold transition-colors"
                  >
                    {triggeringPipeline ? "Triggering..." : "⚡ Run Pipeline Now"}
                  </button>
                  {scenarios.length > 0 && (
                    <button
                      onClick={handleApproveAll}
                      disabled={approvingAll}
                      className="bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white px-4 py-2 rounded text-xs uppercase tracking-widest font-bold transition-colors"
                    >
                      {approvingAll ? "Approving..." : `✓ Approve All (${scenarios.length})`}
                    </button>
                  )}
                  {pipelineMessage && (
                    <p className="text-xs text-breach-blue font-mono">{pipelineMessage}</p>
                  )}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {scenarios.map((s) => (
                  <div key={s.id} className="bg-breach-surface border border-breach-border rounded p-4 hover:border-breach-blue transition-colors flex flex-col justify-between space-y-4">
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[9px] text-breach-muted uppercase tracking-wider font-bold">{s.status}</span>
                        <span className="text-[9px] text-breach-yellow uppercase font-bold font-mono">[Needs Review]</span>
                      </div>
                      <h4 className="text-xs font-bold text-breach-text leading-snug">{s.title}</h4>
                      <p className="text-[10px] text-breach-muted mt-2">Access Vector: {s.initial_access_vector || "—"}</p>
                    </div>
                    <button
                      onClick={() => setReviewScenario(s)}
                      className="w-full bg-breach-blue hover:bg-blue-600 text-black py-1.5 rounded text-[10px] uppercase tracking-widest font-bold transition-colors"
                    >
                      Review & Publish Scenario
                    </button>
                  </div>
                ))}
                {scenarios.length === 0 && (
                  <div className="col-span-full py-12 text-center text-xs text-breach-muted">
                    No scenarios currently require manual review. All uploaded disclosures are processed or published.
                  </div>
                )}
                </div>
              </div>
            )}

            {/* PANEL 4: AUDIT LOGS */}
            {activeTab === "audit" && (
              <div className="bg-breach-surface border border-breach-border rounded overflow-hidden">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-breach-bg border-b border-breach-border uppercase text-[10px] text-breach-muted tracking-widest font-bold font-mono">
                      <th className="px-6 py-3.5">Timestamp</th>
                      <th className="px-6 py-3.5">Event Action</th>
                      <th className="px-6 py-3.5">Client IP</th>
                      <th className="px-6 py-3.5">Event Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-breach-border/60 font-mono text-[11px] text-breach-muted">
                    {auditLogs.map((log) => (
                      <tr key={log.id} className="hover:bg-breach-bg/30">
                        <td className="px-6 py-3.5 text-breach-text whitespace-nowrap">
                          {new Date(log.created_at).toLocaleString()}
                        </td>
                        <td className="px-6 py-3.5 font-bold text-breach-blue">{log.action}</td>
                        <td className="px-6 py-3.5">{log.ip_address || "—"}</td>
                        <td className="px-6 py-3.5 max-w-xs truncate text-[10px]" title={JSON.stringify(log.details)}>
                          {JSON.stringify(log.details)}
                        </td>
                      </tr>
                    ))}
                    {auditLogs.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-6 py-8 text-center text-xs text-breach-muted">
                          No audit events logged yet. Try logging in, deactivating a user, or uploading a document to trigger logs!
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* PANEL 5: COMPLIANCE & ANALYTICS */}
            {activeTab === "compliance" && complianceData && (
              <div className="space-y-8">
                {/* Subscription & Tenant Banner */}
                <div className="bg-breach-surface border border-breach-border rounded p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                  <div>
                    <span className="text-[10px] text-breach-muted uppercase tracking-widest font-mono font-bold">Active Tenant Workspace</span>
                    <h2 className="text-lg font-bold text-breach-text mt-1">{complianceData.organization_name}</h2>
                    <p className="text-xs text-breach-muted mt-0.5">Continuous Compliance Monitoring Console</p>
                  </div>
                  <div className="flex flex-col md:flex-row gap-6 w-full md:w-auto">
                    {/* Subscription Tier */}
                    <div className="bg-breach-bg border border-breach-border rounded px-4 py-3 min-w-[150px]">
                      <span className="text-[9px] text-breach-muted uppercase tracking-wider font-bold">Billing Tier</span>
                      <div className="text-sm font-bold text-breach-blue uppercase mt-1">
                        {complianceData.organization_tier}
                      </div>
                      <span className="text-[9px] text-breach-muted">Workspace License active</span>
                    </div>
                    {/* Document Upload Meter */}
                    <div className="bg-breach-bg border border-breach-border rounded px-4 py-3 min-w-[200px] flex-1 md:flex-initial">
                      <div className="flex justify-between items-center text-[9px] text-breach-muted font-bold uppercase">
                        <span>Disclosure Quota</span>
                        <span>{complianceData.custom_docs_count} / {complianceData.custom_docs_limit === 999 ? "∞" : complianceData.custom_docs_limit}</span>
                      </div>
                      <div className="w-full bg-breach-border h-1.5 rounded-full mt-2 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            complianceData.custom_docs_count >= complianceData.custom_docs_limit ? "bg-breach-accent" : "bg-breach-blue"
                          }`}
                          style={{
                            width: `${Math.min(
                              (complianceData.custom_docs_count / (complianceData.custom_docs_limit || 1)) * 100,
                              100
                            )}%`
                          }}
                        ></div>
                      </div>
                      <span className="text-[9px] text-breach-muted mt-1 block">
                        {complianceData.custom_docs_limit === 999 ? "Unlimited uploads active" : "Upgrade to lift the limit"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* 0. Your Proprietary Simulation Library */}
                <div className="bg-breach-surface border border-breach-blue/40 rounded">
                  <div className="px-6 py-4 border-b border-breach-blue/20 flex items-center justify-between">
                    <div>
                      <span className="text-[9px] text-breach-blue uppercase tracking-widest font-mono font-bold">Competitive Moat</span>
                      <h3 className="text-sm font-bold text-breach-text mt-0.5 uppercase tracking-wider">
                        Your Proprietary Simulation Library
                      </h3>
                    </div>
                    <span className="text-2xl font-bold font-mono text-breach-blue">
                      {complianceData.private_scenarios.length}
                    </span>
                  </div>

                  {complianceData.private_scenarios.length === 0 ? (
                    <div className="px-6 py-8 flex flex-col items-center text-center gap-3">
                      <div className="w-10 h-10 rounded-full border border-breach-border flex items-center justify-center text-breach-muted text-lg">🔒</div>
                      <p className="text-xs text-breach-muted max-w-md leading-relaxed">
                        No proprietary simulations yet. Upload your organization's post-mortem reports and breach disclosures in the{" "}
                        <button
                          onClick={() => setActiveTab("ingest")}
                          className="text-breach-blue underline underline-offset-2 hover:text-blue-400"
                        >
                          Disclosures Ingestion
                        </button>{" "}
                        tab — Claude will convert them into private tabletop scenarios that only your team can access.
                      </p>
                      <p className="text-[10px] text-breach-muted/60 italic max-w-sm">
                        Once built, these simulations become a switching-cost moat: training intelligence drawn from your own breach history that exists nowhere else.
                      </p>
                    </div>
                  ) : (
                    <div className="p-6 space-y-3">
                      <p className="text-[10px] text-breach-muted leading-relaxed mb-4">
                        <span className="text-breach-blue font-bold">{complianceData.private_scenarios.length} proprietary simulation{complianceData.private_scenarios.length !== 1 ? "s" : ""}</span> built from your organization's breach history.{" "}
                        <span className="text-breach-muted/80 italic">This training intelligence exists nowhere else.</span>
                      </p>
                      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                        {complianceData.private_scenarios.map((ps) => (
                          <div key={ps.id} className="bg-breach-bg border border-breach-border rounded p-4 space-y-3">
                            <div className="flex items-start justify-between gap-2">
                              <span className="text-[9px] font-mono text-breach-blue uppercase tracking-widest font-bold">PRIVATE</span>
                              <span className={`text-[9px] font-bold uppercase font-mono ${
                                ps.difficulty === "expert" ? "text-breach-accent" : ps.difficulty === "practitioner" ? "text-breach-yellow" : "text-breach-green"
                              }`}>
                                {ps.difficulty}
                              </span>
                            </div>
                            <h4 className="text-xs font-semibold text-breach-text leading-snug">{ps.title}</h4>
                            <div className="flex flex-wrap gap-1">
                              {ps.mitre_techniques.slice(0, 2).map((t) => (
                                <span key={t} className="text-[9px] bg-breach-surface border border-breach-border px-1.5 py-0.5 rounded font-mono text-green-400">
                                  {t}
                                </span>
                              ))}
                              {ps.nist_controls.slice(0, 1).map((c) => (
                                <span key={c} className="text-[9px] bg-breach-surface border border-breach-border px-1.5 py-0.5 rounded font-mono text-breach-blue">
                                  {c}
                                </span>
                              ))}
                            </div>
                            <div className="grid grid-cols-3 gap-1 text-[10px] text-breach-muted pt-1 border-t border-breach-border/40">
                              <div>
                                <span className="block text-[8px] uppercase tracking-wider">Plays</span>
                                <span className="font-mono font-bold text-breach-text">{ps.play_count}</span>
                              </div>
                              <div>
                                <span className="block text-[8px] uppercase tracking-wider">Avg Score</span>
                                <span className="font-mono font-bold text-breach-text">{ps.avg_score !== null ? `${ps.avg_score}%` : "—"}</span>
                              </div>
                              <div>
                                <span className="block text-[8px] uppercase tracking-wider">Last Run</span>
                                <span className="font-mono text-[9px] text-breach-text">
                                  {ps.last_played_at ? new Date(ps.last_played_at).toLocaleDateString() : "Never"}
                                </span>
                              </div>
                            </div>
                            {ps.source_reference && (
                              <div className="text-[9px] text-breach-muted truncate" title={ps.source_reference}>
                                Source: {ps.source_reference}
                              </div>
                            )}
                            <div className="flex items-center justify-between pt-1 border-t border-breach-border/40">
                              <span className="text-[9px] font-mono text-breach-muted">
                                v{ps.version ?? 1}
                                {ps.version_history && ps.version_history.length > 0 && ` · ${ps.version_history.length} snapshot${ps.version_history.length !== 1 ? "s" : ""}`}
                              </span>
                              <div className="flex gap-1">
                                {ps.version_history && ps.version_history.length > 0 && (
                                  <button
                                    onClick={() => setExpandedVersionId(expandedVersionId === ps.id ? null : ps.id)}
                                    className="text-[8px] text-breach-muted hover:text-breach-text uppercase tracking-wider"
                                  >
                                    {expandedVersionId === ps.id ? "Hide" : "History"}
                                  </button>
                                )}
                                <button
                                  onClick={() => handleSnapshotVersion(ps.id)}
                                  className="text-[8px] bg-breach-surface border border-breach-border px-1.5 py-0.5 rounded text-breach-blue hover:text-white hover:border-breach-blue uppercase tracking-wider font-mono transition-colors"
                                >
                                  + Snapshot
                                </button>
                              </div>
                            </div>
                            {expandedVersionId === ps.id && ps.version_history && (
                              <div className="mt-1 space-y-1 max-h-24 overflow-y-auto">
                                {ps.version_history.map((snap: any, i: number) => (
                                  <div key={i} className="text-[8px] font-mono text-breach-muted bg-breach-bg border border-breach-border/40 rounded px-2 py-1">
                                    v{snap.version} · {new Date(snap.snapshotted_at).toLocaleString()}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* READINESS SCORE + 8-WEEK SPARKLINE */}
                {complianceData.readiness_score !== undefined && (
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    {/* Score dial */}
                    <div className="bg-breach-surface border border-breach-border rounded p-6 flex flex-col items-center justify-center text-center">
                      <span className="text-[9px] text-breach-muted uppercase tracking-widest font-mono font-bold mb-2">Org Readiness Score</span>
                      <div className={`text-6xl font-black font-mono ${
                        complianceData.readiness_score >= 75 ? "text-green-400" :
                        complianceData.readiness_score >= 50 ? "text-breach-yellow" : "text-breach-accent"
                      }`}>
                        {complianceData.readiness_score}
                      </div>
                      <div className="text-[10px] text-breach-muted mt-1">/ 100</div>
                      <div className="w-full bg-breach-bg rounded-full h-1.5 mt-4 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            complianceData.readiness_score >= 75 ? "bg-green-400" :
                            complianceData.readiness_score >= 50 ? "bg-breach-yellow" : "bg-breach-accent"
                          }`}
                          style={{ width: `${complianceData.readiness_score}%` }}
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-2 mt-4 w-full text-left">
                        {Object.entries(complianceData.readiness_components).map(([key, val]) => (
                          <div key={key} className="bg-breach-bg border border-breach-border/60 rounded px-2 py-1.5">
                            <div className="text-[8px] text-breach-muted uppercase tracking-wider">{key.replace(/_/g, " ")}</div>
                            <div className="text-[11px] font-bold font-mono text-breach-text">{val}/25</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* 8-week sparkline */}
                    <div className="lg:col-span-2 bg-breach-surface border border-breach-border rounded p-6">
                      <span className="text-[9px] text-breach-muted uppercase tracking-widest font-mono font-bold">8-Week Training Trend</span>
                      <div className="mt-4 relative h-32">
                        {(() => {
                          const trend = complianceData.readiness_trend;
                          const maxScore = 100;
                          const w = 100 / (trend.length - 1 || 1);
                          const points = trend.map((t, i) => ({
                            x: i * w,
                            y: t.avg_score !== null ? 100 - (t.avg_score / maxScore) * 100 : null,
                            label: t.week,
                            score: t.avg_score,
                            sessions: t.sessions,
                          }));
                          const pathPoints = points.filter((p) => p.y !== null);
                          if (pathPoints.length < 2) return (
                            <div className="flex items-center justify-center h-full text-[10px] text-breach-muted">Not enough data yet</div>
                          );
                          const d = pathPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
                          return (
                            <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
                              <defs>
                                <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
                                  <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
                                </linearGradient>
                              </defs>
                              <path
                                d={`${d} L ${pathPoints[pathPoints.length - 1].x} 100 L ${pathPoints[0].x} 100 Z`}
                                fill="url(#sparkGrad)"
                              />
                              <path d={d} fill="none" stroke="#3b82f6" strokeWidth="2" vectorEffect="non-scaling-stroke" />
                              {pathPoints.map((p, i) => (
                                <circle key={i} cx={p.x} cy={p.y!} r="1.5" fill="#3b82f6" vectorEffect="non-scaling-stroke" />
                              ))}
                            </svg>
                          );
                        })()}
                      </div>
                      <div className="flex justify-between mt-1">
                        {complianceData.readiness_trend.map((t, i) => (
                          <div key={i} className="text-center" style={{ width: `${100 / complianceData.readiness_trend.length}%` }}>
                            <div className="text-[8px] text-breach-muted truncate">{t.week}</div>
                            {t.sessions > 0 && (
                              <div className="text-[8px] font-mono text-breach-blue">{t.avg_score !== null ? `${t.avg_score}%` : "—"}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* RECOMMENDED NEXT SIMULATIONS */}
                {complianceData.recommendations.length > 0 && (
                  <div className="bg-breach-surface border border-breach-border rounded">
                    <div className="px-6 py-4 border-b border-breach-border">
                      <span className="text-[9px] text-breach-muted uppercase tracking-widest font-mono font-bold">AI-Recommended</span>
                      <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider mt-0.5">Next Simulations — Gap-Prioritized</h3>
                    </div>
                    <div className="p-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                      {complianceData.recommendations.map((rec) => (
                        <div key={rec.id} className="bg-breach-bg border border-breach-border rounded p-4 space-y-3">
                          <div className="flex items-center justify-between">
                            <span className={`text-[9px] font-bold uppercase font-mono ${
                              rec.difficulty === "expert" ? "text-breach-accent" : rec.difficulty === "practitioner" ? "text-breach-yellow" : "text-breach-green"
                            }`}>{rec.difficulty}</span>
                            <span className="text-[9px] font-mono text-breach-blue font-bold">{rec.gap_coverage} gaps covered</span>
                          </div>
                          <h4 className="text-xs font-semibold text-breach-text leading-snug">{rec.title}</h4>
                          <div className="text-[9px] text-breach-muted">{rec.industry || "General"} · {rec.estimated_minutes}min</div>
                          {rec.new_nist_controls.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {rec.new_nist_controls.slice(0, 3).map((c) => (
                                <span key={c} className="text-[8px] bg-breach-surface border border-breach-border px-1 py-0.5 rounded font-mono text-breach-blue">{c}</span>
                              ))}
                              {rec.new_nist_controls.length > 3 && (
                                <span className="text-[8px] text-breach-muted">+{rec.new_nist_controls.length - 3}</span>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 1. Global Compliance Scorecard Cards */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                  <div className="bg-breach-surface border border-breach-border rounded p-4">
                    <span className="text-[9px] text-breach-muted uppercase tracking-widest font-bold">Org Avg Score</span>
                    <h4 className="text-2xl font-bold font-mono text-breach-text mt-1">
                      {complianceData.compliance_evidence.length > 0
                        ? `${(
                            complianceData.compliance_evidence.reduce((acc, curr) => acc + (curr.score || 0), 0) /
                            complianceData.compliance_evidence.length
                          ).toFixed(1)}%`
                        : "—"}
                    </h4>
                  </div>
                  <div className="bg-breach-surface border border-breach-border rounded p-4">
                    <span className="text-[9px] text-breach-muted uppercase tracking-widest font-bold">Simulations Run</span>
                    <h4 className="text-2xl font-bold font-mono text-breach-blue mt-1">
                      {complianceData.compliance_evidence.length}
                    </h4>
                  </div>
                  <div className="bg-breach-surface border border-breach-border rounded p-4">
                    <span className="text-[9px] text-breach-muted uppercase tracking-widest font-bold font-mono">MITRE Techniques Covered</span>
                    <h4 className="text-2xl font-bold font-mono text-green-400 mt-1">
                      {new Set(complianceData.scenario_coverage.flatMap((s) => s.mitre_techniques)).size}
                    </h4>
                  </div>
                  <div className="bg-breach-surface border border-breach-border rounded p-4">
                    <span className="text-[9px] text-breach-muted uppercase tracking-widest font-bold font-mono">NIST SP 800-61 Controls</span>
                    <h4 className="text-2xl font-bold font-mono text-breach-accent mt-1">
                      {new Set(complianceData.scenario_coverage.flatMap((s) => s.nist_controls)).size}
                    </h4>
                  </div>
                </div>

                {/* 2. NIST/MITRE Coverage Grid per Scenario */}
                <div className="bg-breach-surface border border-breach-border rounded">
                  <div className="px-6 py-4 border-b border-breach-border flex items-center justify-between">
                    <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider font-mono">
                      NIST CSF & MITRE ATT&CK Scenario Coverage Map
                    </h3>
                  </div>
                  <div className="p-6 overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-breach-bg border-b border-breach-border uppercase text-[10px] text-breach-muted tracking-widest font-bold font-mono">
                          <th className="px-4 py-2.5">Scenario Title</th>
                          <th className="px-4 py-2.5">NIST SP 800-61 Controls</th>
                          <th className="px-4 py-2.5">MITRE ATT&CK Techniques</th>
                          <th className="px-4 py-2.5">Regulatory Frameworks</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-breach-border/60">
                        {complianceData.scenario_coverage.map((scen) => (
                          <tr key={scen.id} className="hover:bg-breach-bg/30">
                            <td className="px-4 py-3 font-semibold text-breach-text max-w-[200px] truncate" title={scen.title}>
                              {scen.title}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-wrap gap-1">
                                {scen.nist_controls.map((c) => (
                                  <span key={c} className="bg-breach-bg border border-breach-border text-[9px] text-breach-blue px-1.5 py-0.5 rounded font-mono">
                                    {c}
                                  </span>
                                ))}
                                {scen.nist_controls.length === 0 && <span className="text-breach-muted italic">—</span>}
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-wrap gap-1">
                                {scen.mitre_techniques.map((t) => (
                                  <span key={t} className="bg-breach-bg border border-breach-border text-[9px] text-green-400 px-1.5 py-0.5 rounded font-mono">
                                    {t}
                                  </span>
                                ))}
                                {scen.mitre_techniques.length === 0 && <span className="text-breach-muted italic">—</span>}
                              </div>
                            </td>
                            <td className="px-4 py-3 font-mono text-breach-muted text-[10px]">
                              {scen.frameworks.join(", ") || "N/A"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* 3. Analyst Performance Tracker */}
                <div className="bg-breach-surface border border-breach-border rounded">
                  <div className="px-6 py-4 border-b border-breach-border">
                    <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider font-mono">
                      Per-Analyst Performance Tracking
                    </h3>
                  </div>
                  <div className="p-6 overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-breach-bg border-b border-breach-border uppercase text-[10px] text-breach-muted tracking-widest font-bold font-mono">
                          <th className="px-4 py-2.5">Team Member</th>
                          <th className="px-4 py-2.5">Sims Completed</th>
                          <th className="px-4 py-2.5">Avg Score</th>
                          <th className="px-4 py-2.5">Decisions Made</th>
                          <th className="px-4 py-2.5">Correct Decisions</th>
                          <th className="px-4 py-2.5">Accuracy Rate</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-breach-border/60">
                        {complianceData.analyst_performance.map((analyst) => (
                          <tr key={analyst.user_id} className="hover:bg-breach-bg/30">
                            <td className="px-4 py-3 font-semibold text-breach-text">
                              <div>{analyst.full_name}</div>
                              <div className="text-[9px] text-breach-muted font-normal">{analyst.email}</div>
                            </td>
                            <td className="px-4 py-3 font-mono text-breach-muted">{analyst.sessions_completed}</td>
                            <td className="px-4 py-3 font-mono font-bold text-breach-text">
                              {analyst.sessions_completed > 0 ? `${analyst.average_score}%` : "—"}
                            </td>
                            <td className="px-4 py-3 font-mono text-breach-muted">{analyst.decisions_made}</td>
                            <td className="px-4 py-3 font-mono text-green-400">{analyst.decisions_correct}</td>
                            <td className="px-4 py-3 font-mono">
                              <span className={analyst.accuracy_rate >= 80 ? "text-green-400 font-bold" : (analyst.accuracy_rate >= 60 ? "text-breach-yellow font-bold" : "text-breach-accent font-bold")}>
                                {analyst.decisions_made > 0 ? `${analyst.accuracy_rate}%` : "—"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* 4. Scenario Calibration & Evidence Log row */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Calibration */}
                  <div className="bg-breach-surface border border-breach-border rounded">
                    <div className="px-6 py-4 border-b border-breach-border">
                      <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider font-mono">
                        Difficulty Calibration Recommendation
                      </h3>
                    </div>
                    <div className="p-6 space-y-4 max-h-[400px] overflow-y-auto">
                      {complianceData.calibrations.map((cal) => (
                        <div key={cal.scenario_id} className="bg-breach-bg border border-breach-border rounded p-3 text-xs space-y-2">
                          <div className="flex justify-between items-start">
                            <span className="font-semibold text-breach-text truncate max-w-[180px]" title={cal.title}>
                              {cal.title}
                            </span>
                            <span className={`px-1.5 py-0.5 rounded text-[8px] uppercase tracking-wider font-mono font-bold ${
                              cal.is_calibrated ? "bg-green-500/10 border border-green-500/30 text-green-400" : "bg-breach-yellow/10 border border-breach-yellow/30 text-breach-yellow"
                            }`}>
                              {cal.is_calibrated ? "CALIBRATED" : "RE-CALIBRATION REC"}
                            </span>
                          </div>
                          <div className="grid grid-cols-3 gap-2 text-[10px] text-breach-muted">
                            <div>
                              <span>Designed Diff:</span>
                              <span className="block font-bold text-breach-text uppercase mt-0.5">{cal.designed_difficulty}</span>
                            </div>
                            <div>
                              <span>Calibrated Diff:</span>
                              <span className="block font-bold text-breach-accent uppercase mt-0.5">{cal.calibrated_difficulty}</span>
                            </div>
                            <div>
                              <span>Org Avg Score:</span>
                              <span className="block font-bold text-breach-blue mt-0.5">
                                {cal.avg_score !== null ? `${cal.avg_score}%` : "No Plays"}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Evidence & CSV Export */}
                  <div className="bg-breach-surface border border-breach-border rounded flex flex-col justify-between">
                    <div>
                      <div className="px-6 py-4 border-b border-breach-border flex justify-between items-center">
                        <h3 className="text-xs font-bold text-breach-text uppercase tracking-wider font-mono">
                          Auditor Training Compliance Logs
                        </h3>
                        <button
                          onClick={handleExportCSV}
                          disabled={exportingCSV}
                          className="bg-breach-accent hover:bg-red-600 disabled:bg-breach-accent/50 text-white px-3 py-1 rounded text-[10px] uppercase font-bold tracking-widest transition-colors flex items-center gap-1.5"
                        >
                          {exportingCSV ? (
                            <>
                              <span className="w-2.5 h-2.5 border border-white border-t-transparent rounded-full animate-spin"></span>
                              Exporting...
                            </>
                          ) : (
                            <>📄 Export CSV Package</>
                          )}
                        </button>
                      </div>
                      <div className="p-6 space-y-3 max-h-[300px] overflow-y-auto pr-1">
                        {complianceData.compliance_evidence.map((evidence, idx) => (
                          <div key={idx} className="bg-breach-bg border border-breach-border/60 rounded p-3 text-xs space-y-1">
                            <div className="flex justify-between items-center">
                              <span className="font-semibold text-breach-text truncate max-w-[150px]">{evidence.scenario_title}</span>
                              <span className="font-mono text-green-400 font-bold">{evidence.score !== null ? `${evidence.score}%` : "—"}</span>
                            </div>
                            <div className="text-[9px] text-breach-muted">
                              Completed: {new Date(evidence.completed_at).toLocaleDateString()} | Participants: {evidence.participant_count}
                            </div>
                            <div className="text-[9px] text-breach-muted leading-tight border-t border-breach-border/40 pt-1 mt-1 italic">
                              {evidence.audit_notes}
                            </div>
                          </div>
                        ))}
                        {complianceData.compliance_evidence.length === 0 && (
                          <p className="text-xs text-breach-muted text-center py-6">
                            No tabletop training exercises completed in this organization yet.
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="p-6 border-t border-breach-border bg-breach-bg/30 text-[10px] text-breach-muted leading-normal">
                      🛡️ These tabletop exercise logs serve as official training evidence under annual compliance parameters defined in **SOC 2 Type II (CC7.3)**, **NIST SP 800-53 (AT-3)**, and **ISO 27001 (A.7.2.2)**.
                    </div>
                  </div>
                </div>
              </div>
            )}

          </div>
        )}
      </div>

      {/* Scenario Review Modal Portal */}
      {reviewScenario && (
        <ScenarioReviewModal
          scenario={reviewScenario}
          onClose={() => setReviewScenario(null)}
          onApproved={() => {
            setReviewScenario(null);
            loadTabData();
          }}
        />
      )}
    </div>
  );
}
