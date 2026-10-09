"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { completeLogin, consumePostLoginRedirect } from "@/lib/auth";
import { LoadingBlock, InlineBanner } from "@/components/ui/States";

function CallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const errorParam = searchParams.get("error");
    const errorDescription = searchParams.get("error_description");

    if (errorParam) {
      setError(errorDescription || `Keycloak returned an error: ${errorParam}`);
      return;
    }
    if (!code || !state) {
      setError("Missing authorization code. Please try signing in again.");
      return;
    }

    completeLogin(code, state).then((result) => {
      if (result.ok) {
        router.replace(consumePostLoginRedirect());
      } else {
        setError(result.error);
      }
    });
  }, [searchParams, router]);

  if (error) {
    return (
      <div className="authCard">
        <InlineBanner kind="error">{error}</InlineBanner>
        <a className="btn btnPrimary" href="/login" style={{ justifyContent: "center" }}>
          Back to sign-in
        </a>
      </div>
    );
  }

  return <LoadingBlock label="Completing sign-in…" />;
}

export default function LoginCallbackPage() {
  return (
    <div className="authScreen">
      <Suspense fallback={<LoadingBlock label="Loading…" />}>
        <CallbackInner />
      </Suspense>
    </div>
  );
}
