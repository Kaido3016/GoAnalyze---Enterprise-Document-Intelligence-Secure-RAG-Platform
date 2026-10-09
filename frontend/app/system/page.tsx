"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, CheckCircle2, RefreshCcw, XCircle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBlock, LoadingBlock } from "@/components/ui/States";
import { config } from "@/lib/config";
import { systemApi } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

type Slot<T> = { status: "loading" | "success" | "error"; data: T | null; error: unknown; checkedAt: string | null };

function initialSlot<T>(): Slot<T> {
  return { status: "loading", data: null, error: null, checkedAt: null };
}

export default function SystemPage() {
  const [health, setHealth] = useState<Slot<Record<string, string>>>(initialSlot());
  const [ready, setReady] = useState<Slot<Record<string, unknown>>>(initialSlot());
  const [metrics, setMetrics] = useState<Slot<unknown>>(initialSlot());

  const refresh = useCallback(() => {
    setHealth((s) => ({ ...s, status: "loading" }));
    setReady((s) => ({ ...s, status: "loading" }));
    setMetrics((s) => ({ ...s, status: "loading" }));

    const now = () => new Date().toISOString();

    systemApi
      .health()
      .then((data) => setHealth({ status: "success", data, error: null, checkedAt: now() }))
      .catch((error) => setHealth({ status: "error", data: null, error, checkedAt: now() }));

    systemApi
      .ready()
      .then((data) => setReady({ status: "success", data, error: null, checkedAt: now() }))
      .catch((error) => setReady({ status: "error", data: null, error, checkedAt: now() }));

    systemApi
      .metrics()
      .then((data) => setMetrics({ status: "success", data, error: null, checkedAt: now() }))
      .catch((error) => setMetrics({ status: "error", data: null, error, checkedAt: now() }));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <AppShell>
      <div className="pageHeading">
        <div>
          <h1>System Health</h1>
          <p>
            Live status from <code className="mono">{config.apiBaseUrl}</code>.
          </p>
        </div>
        <div className="pageActions">
          <button className="btn btnPrimary" onClick={refresh}>
            <RefreshCcw size={15} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid2">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <StatusCard title="API Health (/health)" icon={Activity} slot={health} onRetry={refresh} />
          <StatusCard title="Readiness (/ready)" icon={CheckCircle2} slot={ready} onRetry={refresh} />
        </div>
        <MetricsCard slot={metrics} onRetry={refresh} />
      </div>
    </AppShell>
  );
}

function StatusCard<T extends Record<string, unknown>>({
  title,
  icon: Icon,
  slot,
  onRetry
}: {
  title: string;
  icon: typeof Activity;
  slot: Slot<T>;
  onRetry: () => void;
}) {
  return (
    <div className="card">
      <div className="cardHeader">
        <h2>{title}</h2>
        <Icon size={16} color="var(--muted-2)" />
      </div>
      {slot.status === "loading" && <LoadingBlock label="Checking…" />}
      {slot.status === "error" && <ErrorBlock error={slot.error} onRetry={onRetry} />}
      {slot.status === "success" && slot.data && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <CheckCircle2 size={16} color="var(--success)" />
            <span style={{ fontWeight: 700 }}>Reachable</span>
          </div>
          <dl style={{ display: "grid", gridTemplateColumns: "160px 1fr", rowGap: 6, fontSize: 13, margin: 0 }}>
            {Object.entries(slot.data).map(([key, value]) => (
              <div key={key} style={{ display: "contents" }}>
                <dt style={{ color: "var(--muted)", textTransform: "capitalize" }}>{key.replace(/_/g, " ")}</dt>
                <dd style={{ margin: 0 }}>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
              </div>
            ))}
          </dl>
          {slot.checkedAt && (
            <p style={{ fontSize: 11.5, color: "var(--muted-2)", marginTop: 10 }}>
              Last checked {formatDateTime(slot.checkedAt)}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function MetricsCard({ slot, onRetry }: { slot: Slot<unknown>; onRetry: () => void }) {
  return (
    <div className="card">
      <div className="cardHeader">
        <h2>Metrics (/metrics)</h2>
        {slot.status === "error" ? (
          <XCircle size={16} color="var(--danger)" />
        ) : (
          <Activity size={16} color="var(--muted-2)" />
        )}
      </div>
      {slot.status === "loading" && <LoadingBlock label="Fetching metrics…" />}
      {slot.status === "error" && <ErrorBlock error={slot.error} onRetry={onRetry} />}
      {slot.status === "success" && (
        <pre
          style={{
            fontSize: 12,
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: 6,
            padding: 12,
            maxHeight: 420,
            overflow: "auto"
          }}
        >
          {typeof slot.data === "string" ? slot.data : JSON.stringify(slot.data, null, 2)}
        </pre>
      )}
      {slot.checkedAt && slot.status === "success" && (
        <p style={{ fontSize: 11.5, color: "var(--muted-2)", marginTop: 10 }}>
          Last checked {formatDateTime(slot.checkedAt)}
        </p>
      )}
    </div>
  );
}
