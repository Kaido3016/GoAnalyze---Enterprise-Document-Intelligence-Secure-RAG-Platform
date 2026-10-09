"use client";

import { useCallback, useState } from "react";
import { ApiError, documentsApi } from "@/lib/api";
import type {
  DocumentIngestRequest,
  DocumentProcessingResult,
  DocumentRecord,
  SearchParams,
  SearchResponse
} from "@/lib/types";
import type { AsyncStatus } from "./useSearch";

/**
 * The backend has no `GET /v1/documents` list endpoint (see
 * FRONTEND_BACKEND_GAPS.md), so the Documents listing page reuses
 * `GET /v1/documents/search` with an empty query, which is the closest
 * real, working equivalent (full-text search that also matches by
 * recency when the query is blank).
 */
export function useDocumentsList() {
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);

  const load = useCallback(async (params: SearchParams = {}) => {
    setStatus("loading");
    setError(null);
    try {
      const result = await documentsApi.search({ q: "", ...params });
      setData(result);
      setStatus("success");
    } catch (err) {
      setError(err as Error);
      setStatus("error");
    }
  }, []);

  return { status, data, error, load };
}

export function useIngestDocument() {
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [record, setRecord] = useState<DocumentRecord | null>(null);

  const ingest = useCallback(async (payload: DocumentIngestRequest) => {
    setStatus("loading");
    setError(null);
    try {
      const result = await documentsApi.ingest(payload);
      setRecord(result);
      setStatus("success");
      return result;
    } catch (err) {
      setError(err as Error);
      setStatus("error");
      throw err;
    }
  }, []);

  return { status, error, record, ingest };
}

export function useProcessDocument() {
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [result, setResult] = useState<DocumentProcessingResult | null>(null);

  const process = useCallback(async (documentId: string) => {
    setStatus("loading");
    setError(null);
    try {
      const res = await documentsApi.process(documentId);
      setResult(res);
      setStatus("success");
      return res;
    } catch (err) {
      setError(err as Error);
      setStatus("error");
      throw err;
    }
  }, []);

  return { status, error, result, process };
}
