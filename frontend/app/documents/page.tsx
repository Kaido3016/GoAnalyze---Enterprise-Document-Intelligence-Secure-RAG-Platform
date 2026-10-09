"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileUp } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { DocumentFilters, type DocumentFiltersValue } from "@/components/search/SearchFilters";
import { DocumentTable } from "@/components/documents/DocumentTable";
import { Pagination } from "@/components/ui/Pagination";
import { EmptyBlock, ErrorBlock, GapNote, TableSkeleton } from "@/components/ui/States";
import { useDocumentsList } from "@/hooks/useDocuments";

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  const { status, data, error, load } = useDocumentsList();
  const [filters, setFilters] = useState<DocumentFiltersValue>({ q: "", classification: "", content_type: "" });
  const [page, setPage] = useState(1);

  function runSearch(nextPage = 1) {
    setPage(nextPage);
    load({
      q: filters.q,
      classification: filters.classification || undefined,
      content_type: filters.content_type || undefined,
      page: nextPage,
      page_size: PAGE_SIZE
    });
  }

  useEffect(() => {
    runSearch(1);
  }, []);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <AppShell>
      <div className="pageHeading">
        <div>
          <h1>Documents</h1>
          <p>Full-text search across ingested documents, backed by {data?.backend ?? "OpenSearch / database fallback"}.</p>
        </div>
        <div className="pageActions">
          <Link href="/documents/upload" className="btn btnPrimary">
            <FileUp size={15} /> Upload Document
          </Link>
        </div>
      </div>

      <GapNote>
        There is no <code className="mono">GET /v1/documents</code> listing endpoint. This page
        uses <code className="mono">GET /v1/documents/search</code> with an empty query as the
        real, working equivalent — see FRONTEND_BACKEND_GAPS.md.
      </GapNote>

      <DocumentFilters value={filters} onChange={setFilters} onSubmit={() => runSearch(1)} />

      {status === "loading" && <TableSkeleton rows={8} />}
      {status === "error" && <ErrorBlock error={error} onRetry={() => runSearch(page)} />}
      {status === "success" && data && data.results.length === 0 && (
        <EmptyBlock
          title="No documents found"
          description="Try a different query or filter, or upload a new document."
          action={
            <Link href="/documents/upload" className="btn btnPrimary btnSm">
              Upload a document
            </Link>
          }
        />
      )}
      {status === "success" && data && data.results.length > 0 && (
        <>
          <DocumentTable results={data.results} />
          <Pagination page={data.page} totalPages={totalPages} total={data.total} onChange={runSearch} />
        </>
      )}
    </AppShell>
  );
}
