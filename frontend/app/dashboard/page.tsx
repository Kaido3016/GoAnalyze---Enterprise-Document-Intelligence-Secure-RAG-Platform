"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileUp, Search, Sparkles } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { DashboardStats } from "@/components/dashboard/DashboardStats";
import { RecentDocuments } from "@/components/dashboard/RecentDocuments";
import { ActivityFeed } from "@/components/dashboard/ActivityFeed";
import { ProcessingStatus } from "@/components/dashboard/ProcessingStatus";
import { RiskOverview } from "@/components/dashboard/RiskOverview";
import { useSearch } from "@/hooks/useSearch";
import { useAudit } from "@/hooks/useAudit";
import { systemApi } from "@/lib/api";

export default function DashboardPage() {
  const search = useSearch();
  const audit = useAudit();
  const [apiReady, setApiReady] = useState<boolean | null>(null);

  useEffect(() => {
    search.search({ q: "", page: 1, page_size: 10 });
    audit.load(1, 10);
    systemApi
      .ready()
      .then(() => setApiReady(true))
      .catch(() => setApiReady(false));
  }, []);

  const loading = search.status === "loading" && audit.status === "loading";

  return (
    <AppShell>
      <div className="pageHeading">
        <div>
          <h1>Dashboard</h1>
          <p>Operational overview of document intelligence, governance, and system health.</p>
        </div>
        <div className="pageActions">
          <Link href="/documents/upload" className="btn btnPrimary">
            <FileUp size={15} /> Upload Document
          </Link>
          <Link href="/search" className="btn">
            <Search size={15} /> Search
          </Link>
          <Link href="/ai-research" className="btn">
            <Sparkles size={15} /> AI Research
          </Link>
        </div>
      </div>

      <DashboardStats
        totalDocuments={search.data?.total ?? null}
        apiReady={apiReady}
        auditTotal={audit.data?.total ?? null}
        loading={loading}
      />

      <div className="grid2">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <RecentDocuments
            status={search.status}
            hits={search.data?.results ?? []}
            error={search.error}
            onRetry={() => search.search({ q: "", page: 1, page_size: 10 })}
          />
          <ProcessingStatus />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <ActivityFeed
            status={audit.status}
            events={audit.data?.items ?? []}
            error={audit.error}
            onRetry={() => audit.load(1, 10)}
          />
          <RiskOverview />
        </div>
      </div>
    </AppShell>
  );
}
