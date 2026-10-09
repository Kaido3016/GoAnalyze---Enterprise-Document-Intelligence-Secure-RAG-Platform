"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FileSearch, PlayCircle, UploadCloud } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { DocumentMetadata } from "@/components/documents/DocumentMetadata";
import { DownloadButton } from "@/components/documents/DownloadButton";
import { InlineBanner } from "@/components/ui/States";
import { useProcessDocument } from "@/hooks/useDocuments";
import { getCachedDocument } from "@/lib/documentCache";
import type { CachedDocument } from "@/lib/documentCache";

export default function DocumentDetailPage() {
  const params = useParams<{ document_id: string }>();
  const documentId = params.document_id;
  const router = useRouter();
  const [doc, setDoc] = useState<CachedDocument | null>(null);
  const { status, error, result, process } = useProcessDocument();

  useEffect(() => {
    setDoc(getCachedDocument(documentId));
  }, [documentId]);

  return (
    <AppShell>
      <div className="pageHeading">
        <div>
          <h1>{doc?.filename ?? "Document"}</h1>
          <p className="mono">{documentId}</p>
        </div>
        <div className="pageActions">
          <DownloadButton documentId={documentId} filename={doc?.filename} className="btn" />
          <Link href={`/analysis/${documentId}`} className="btn">
            <FileSearch size={15} /> Open Analysis
          </Link>
        </div>
      </div>

      <div className="grid2">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <DocumentMetadata doc={doc} documentId={documentId} />

          <div className="card">
            <div className="cardHeader">
              <h2>Content</h2>
            </div>
            <p style={{ fontSize: 13, color: "var(--muted)" }}>
              The backend stores document content in object storage. Use Download to retrieve the
              current version, or replace it via{" "}
              <code className="mono">PUT /v1/documents/{"{document_id}"}/content</code> from the{" "}
              <Link href="/documents/upload">upload flow</Link>.
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <DownloadButton documentId={documentId} filename={doc?.filename} className="btn btnSm" />
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card">
            <div className="cardHeader">
              <h2>Processing</h2>
            </div>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Runs OCR, classification, metadata/entity extraction, compliance analysis, risk
              scoring, vector indexing, workflow routing, and audit logging synchronously.
            </p>
            {error && <InlineBanner kind="error">{error.message}</InlineBanner>}
            {result?.completed && (
              <InlineBanner kind="success">
                Processing completed — {result.stages.length} stage(s) run.
              </InlineBanner>
            )}
            <button
              className="btn btnPrimary"
              disabled={status === "loading"}
              onClick={() => process(documentId)}
            >
              <PlayCircle size={15} /> {status === "loading" ? "Processing…" : "Run Processing"}
            </button>
            {result && (
              <button
                className="btn btnSm"
                style={{ marginLeft: 8 }}
                onClick={() => router.push(`/analysis/${documentId}`)}
              >
                View results
              </button>
            )}
          </div>

          <div className="card">
            <div className="cardHeader">
              <h2>Upload New Version</h2>
            </div>
            <p style={{ fontSize: 13, color: "var(--muted)" }}>
              To replace this document&apos;s content, use the upload flow with the same document
              context.
            </p>
            <Link href="/documents/upload" className="btn btnSm">
              <UploadCloud size={14} /> Go to Upload
            </Link>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
