"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { PlayCircle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ProcessingPipeline } from "@/components/analysis/ProcessingPipeline";
import {
  AnalysisOverview,
  ClassificationResult,
  EntitiesPanel,
  RiskScore,
  WorkflowPanel
} from "@/components/analysis/AnalysisPanels";
import { CompliancePanel } from "@/components/analysis/CompliancePanel";
import { InlineBanner } from "@/components/ui/States";
import { useProcessDocument } from "@/hooks/useDocuments";
import { getCachedDocument } from "@/lib/documentCache";

export default function AnalysisPage() {
  const params = useParams<{ document_id: string }>();
  const documentId = params.document_id;
  const { status, error, result, process } = useProcessDocument();
  const [filename, setFilename] = useState<string | null>(null);

  useEffect(() => {
    setFilename(getCachedDocument(documentId)?.filename ?? null);
  }, [documentId]);

  return (
    <AppShell>
      <div className="pageHeading">
        <div>
          <h1>Document Analysis</h1>
          <p>
            {filename ?? "Document"} · <span className="mono">{documentId}</span>
          </p>
        </div>
        <div className="pageActions">
          <Link href={`/documents/${documentId}`} className="btn">
            Document details
          </Link>
          <button className="btn btnPrimary" disabled={status === "loading"} onClick={() => process(documentId)}>
            <PlayCircle size={15} /> {status === "loading" ? "Processing…" : result ? "Re-run Processing" : "Run Processing"}
          </button>
        </div>
      </div>

      {error && <InlineBanner kind="error">{error.message}</InlineBanner>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="cardHeader">
          <h2>Processing Pipeline</h2>
        </div>
        <ProcessingPipeline stages={result?.stages ?? null} />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="cardHeader">
          <h2>Overview</h2>
        </div>
        <AnalysisOverview result={result} />
      </div>

      <div className="grid2">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <ClassificationResult label={result?.classification_label} />
          <EntitiesPanel entities={result?.extracted_entities} />
          <CompliancePanel stages={result?.stages ?? null} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <RiskScore score={result?.risk_score} />
          <WorkflowPanel queue={result?.workflow_queue} />
        </div>
      </div>
    </AppShell>
  );
}
