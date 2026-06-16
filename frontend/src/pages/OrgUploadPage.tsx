import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";

interface DocOut {
  id: string;
  filename: string;
  status: "processing" | "completed" | "failed";
  created_at: string;
  extracted_scenario_id: string | null;
}

interface PrivateScenario {
  id: string;
  title: string;
  difficulty: string | null;
  industry_vertical: string | null;
  extraction_confidence: number | null;
  status: string;
  created_at: string;
}

const STATUS_STYLES: Record<string, string> = {
  processing: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
  completed: "bg-green-500/10 text-green-400 border-green-500/30",
  failed: "bg-red-500/10 text-red-400 border-red-500/30",
};

const CONF_COLOR = (c: number) =>
  c >= 0.7 ? "text-green-400" : c >= 0.5 ? "text-yellow-400" : "text-red-400";

export default function OrgUploadPage() {
  const qc = useQueryClient();
  const [dragging, setDragging] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: docs = [], isLoading: docsLoading } = useQuery<DocOut[]>({
    queryKey: ["org-documents"],
    queryFn: async () => (await axiosInstance.get("/orgs/documents")).data,
    refetchInterval: 8000,
  });

  const { data: scenarios = [], isLoading: scenLoading } = useQuery<PrivateScenario[]>({
    queryKey: ["private-scenarios"],
    queryFn: async () => (await axiosInstance.get("/orgs/private-scenarios")).data,
    refetchInterval: 10000,
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const res = await axiosInstance.post("/orgs/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return res.data;
    },
    onSuccess: (data) => {
      setUploadError("");
      setUploadSuccess(`"${data.filename}" uploaded — Claude is building your private scenario. Refresh in ~90 seconds.`);
      qc.invalidateQueries({ queryKey: ["org-documents"] });
      setTimeout(() => setUploadSuccess(""), 8000);
    },
    onError: (err: any) => {
      setUploadError(err?.message || "Upload failed. Please try again.");
    },
  });

  const handleFile = useCallback(
    (file: File) => {
      setUploadError("");
      setUploadSuccess("");
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!["pdf", "docx", "txt"].includes(ext)) {
        setUploadError("Only PDF, DOCX, or TXT files are accepted.");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setUploadError("File must be under 10 MB.");
        return;
      }
      uploadMutation.mutate(file);
    },
    [uploadMutation]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  };

  const processingCount = docs.filter((d) => d.status === "processing").length;
  const completedCount = docs.filter((d) => d.status === "completed").length;

  return (
    <div className="min-h-screen bg-breach-bg text-breach-text p-6">
      <div className="max-w-5xl mx-auto space-y-8">

        {/* Header */}
        <div className="border-b border-breach-border pb-5">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-2xl">🏢</span>
            <div>
              <h1 className="text-lg font-bold text-breach-text uppercase tracking-widest">Private Org Scenarios</h1>
              <p className="text-xs text-breach-muted mt-0.5">
                Upload your incident post-mortems — Claude generates private simulations visible only to your org
              </p>
            </div>
          </div>
          <div className="flex gap-4 mt-4 text-xs">
            <div className="bg-breach-surface border border-breach-border rounded px-3 py-2">
              <span className="text-breach-muted uppercase tracking-wider text-[9px] block">Documents</span>
              <span className="font-bold font-mono text-sm">{docs.length}</span>
            </div>
            <div className="bg-breach-surface border border-breach-border rounded px-3 py-2">
              <span className="text-breach-muted uppercase tracking-wider text-[9px] block">Processing</span>
              <span className="font-bold font-mono text-sm text-yellow-400">{processingCount}</span>
            </div>
            <div className="bg-breach-surface border border-breach-border rounded px-3 py-2">
              <span className="text-breach-muted uppercase tracking-wider text-[9px] block">Scenarios</span>
              <span className="font-bold font-mono text-sm text-green-400">{scenarios.length}</span>
            </div>
          </div>
        </div>

        {/* Upload Drop Zone */}
        <div className="space-y-3">
          <div className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">Upload Document</div>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`relative border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-all ${
              dragging
                ? "border-breach-accent bg-breach-accent/5 scale-[1.01]"
                : "border-breach-border hover:border-breach-blue hover:bg-breach-surface/50"
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt"
              className="hidden"
              onChange={onInputChange}
            />
            {uploadMutation.isPending ? (
              <div className="flex flex-col items-center gap-3">
                <div className="w-10 h-10 border-4 border-breach-accent border-t-transparent rounded-full animate-spin" />
                <p className="text-sm font-bold text-breach-text uppercase tracking-widest">Uploading...</p>
              </div>
            ) : (
              <>
                <div className="text-4xl mb-3">📄</div>
                <p className="text-sm font-bold text-breach-text uppercase tracking-widest mb-1">
                  Drop your post-mortem document here
                </p>
                <p className="text-xs text-breach-muted">PDF · DOCX · TXT &nbsp;·&nbsp; Max 10 MB &nbsp;·&nbsp; Click to browse</p>
                <div className="mt-4 inline-flex items-center gap-2 bg-breach-accent/10 border border-breach-accent/30 px-4 py-1.5 rounded text-xs text-breach-accent font-bold uppercase tracking-widest">
                  Select File
                </div>
              </>
            )}
          </div>

          {uploadError && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-xs p-3 rounded">
              {uploadError}
            </div>
          )}
          {uploadSuccess && (
            <div className="bg-green-500/10 border border-green-500/30 text-green-400 text-xs p-3 rounded">
              ✓ {uploadSuccess}
            </div>
          )}
        </div>

        {/* What happens section */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { step: "1", icon: "📤", title: "You Upload", body: "Incident report, post-mortem PDF, or internal runbook. Any format works." },
            { step: "2", icon: "🧠", title: "Claude Extracts", body: "AI reads the document, identifies attack vectors, MITRE techniques, and decision points." },
            { step: "3", icon: "🔒", title: "Private Scenario", body: "A full tabletop simulation appears in your org's private library — invisible to other orgs." },
          ].map(({ step, icon, title, body }) => (
            <div key={step} className="bg-breach-surface border border-breach-border rounded p-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs bg-breach-accent/20 text-breach-accent border border-breach-accent/30 rounded-full w-5 h-5 flex items-center justify-center font-bold font-mono">{step}</span>
                <span className="text-xl">{icon}</span>
                <span className="text-xs font-bold text-breach-text uppercase tracking-wider">{title}</span>
              </div>
              <p className="text-xs text-breach-muted leading-relaxed">{body}</p>
            </div>
          ))}
        </div>

        {/* Uploaded Documents */}
        {docs.length > 0 && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">Uploaded Documents</div>
              {processingCount > 0 && (
                <span className="text-[10px] text-yellow-400 animate-pulse">● Processing {processingCount} document{processingCount > 1 ? "s" : ""}</span>
              )}
            </div>
            <div className="space-y-2">
              {docsLoading ? (
                <div className="text-xs text-breach-muted p-4">Loading...</div>
              ) : (
                docs.map((doc) => (
                  <div key={doc.id} className="bg-breach-surface border border-breach-border rounded p-4 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-base shrink-0">{doc.filename.endsWith(".pdf") ? "📄" : doc.filename.endsWith(".docx") ? "📝" : "📃"}</span>
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-breach-text truncate">{doc.filename}</div>
                        <div className="text-[10px] text-breach-muted">{new Date(doc.created_at).toLocaleDateString()}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className={`text-[10px] border px-2 py-0.5 rounded uppercase font-bold tracking-wider ${STATUS_STYLES[doc.status] ?? ""}`}>
                        {doc.status === "processing" ? "⏳ Processing" : doc.status === "completed" ? "✓ Done" : "✗ Failed"}
                      </span>
                      {doc.extracted_scenario_id && (
                        <a
                          href={`/scenarios`}
                          className="text-[10px] bg-breach-blue/10 border border-breach-blue/30 text-breach-blue px-2 py-0.5 rounded font-bold uppercase tracking-wider hover:bg-breach-blue/20 transition-colors"
                        >
                          View Scenario →
                        </a>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Private Scenarios */}
        <div className="space-y-3">
          <div className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">Private Scenario Library</div>
          {scenLoading ? (
            <div className="text-xs text-breach-muted p-4">Loading scenarios...</div>
          ) : scenarios.length === 0 ? (
            <div className="bg-breach-surface border border-dashed border-breach-border rounded p-8 text-center">
              <div className="text-3xl mb-3">🔒</div>
              <p className="text-xs font-bold text-breach-text uppercase tracking-wider mb-1">No Private Scenarios Yet</p>
              <p className="text-xs text-breach-muted max-w-sm mx-auto leading-relaxed">
                Upload your first incident post-mortem above — Claude will extract a full simulation scenario that only your team can access.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {scenarios.map((s) => (
                <div key={s.id} className="bg-breach-surface border border-breach-border rounded p-5 space-y-3 hover:border-breach-blue transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[9px] bg-purple-500/10 text-purple-400 border border-purple-500/20 px-1.5 py-0.5 rounded uppercase font-bold tracking-widest">Private</span>
                        {s.status === "approved" && (
                          <span className="text-[9px] bg-green-500/10 text-green-400 border border-green-500/20 px-1.5 py-0.5 rounded uppercase font-bold tracking-widest">Ready</span>
                        )}
                      </div>
                      <h3 className="text-sm font-bold text-breach-text leading-tight">{s.title}</h3>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 text-[10px]">
                    {s.industry_vertical && (
                      <span className="bg-breach-bg border border-breach-border px-2 py-0.5 rounded text-breach-muted">{s.industry_vertical}</span>
                    )}
                    {s.difficulty && (
                      <span className="bg-breach-bg border border-breach-border px-2 py-0.5 rounded text-breach-muted capitalize">{s.difficulty}</span>
                    )}
                    {s.extraction_confidence !== null && (
                      <span className={`font-mono font-bold ${CONF_COLOR(s.extraction_confidence)}`}>
                        {Math.round(s.extraction_confidence * 100)}% confidence
                      </span>
                    )}
                  </div>
                  <a
                    href="/scenarios"
                    className="block w-full text-center text-[10px] uppercase tracking-widest font-bold bg-breach-accent/10 border border-breach-accent/30 text-breach-accent px-3 py-1.5 rounded hover:bg-breach-accent/20 transition-colors"
                  >
                    Launch Simulation →
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
