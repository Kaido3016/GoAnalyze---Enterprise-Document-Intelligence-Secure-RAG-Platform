"use client";

import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { AuditTable } from "@/components/audit/AuditTable";
import { Pagination } from "@/components/ui/Pagination";
import { EmptyBlock, ErrorBlock, TableSkeleton } from "@/components/ui/States";
import { useAudit } from "@/hooks/useAudit";

const PAGE_SIZE = 25;

export default function AuditPage() {
  const { status, data, error, load } = useAudit();
  const [page, setPage] = useState(1);

  useEffect(() => {
    load(1, PAGE_SIZE);
  }, []);

  function goToPage(p: number) {
    setPage(p);
    load(p, PAGE_SIZE);
  }

  return (
    <AppShell>
      <div className="pageHeading">
        <div>
          <h1>Audit Log</h1>
          <p>
            Governance and traceability events from <code className="mono">GET /v1/audit</code>.
          </p>
        </div>
        <div className="pageActions">
          <button className="btn" onClick={() => goToPage(page)}>
            <RefreshCcw size={14} /> Refresh
          </button>
        </div>
      </div>

      {status === "loading" && <TableSkeleton rows={10} />}
      {status === "error" && <ErrorBlock error={error} onRetry={() => goToPage(page)} />}
      {status === "success" && data && data.items.length === 0 && (
        <EmptyBlock title="No audit events" description="Events will appear here as actions are taken across the platform." />
      )}
      {status === "success" && data && data.items.length > 0 && (
        <>
          <AuditTable events={data.items} />
          <Pagination page={data.page} totalPages={data.total_pages} total={data.total} onChange={goToPage} />
        </>
      )}
    </AppShell>
  );
}
