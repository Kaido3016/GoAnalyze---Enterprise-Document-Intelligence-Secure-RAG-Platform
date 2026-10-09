"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type DecodedUser,
  getCurrentUser,
  isAuthenticated,
  login as loginRedirect,
  logout as logoutRedirect,
  refreshTokens
} from "@/lib/auth";

export function useAuth() {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [user, setUser] = useState<DecodedUser | null>(null);

  const refresh = useCallback(async () => {
    let ok = isAuthenticated();
    if (!ok) {
      const refreshed = await refreshTokens();
      ok = Boolean(refreshed);
    }
    setAuthenticated(ok);
    setUser(ok ? getCurrentUser() : null);
    setReady(true);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    ready,
    authenticated,
    user,
    roles: user?.realm_access?.roles ?? [],
    login: loginRedirect,
    logout: logoutRedirect,
    refresh
  };
}
