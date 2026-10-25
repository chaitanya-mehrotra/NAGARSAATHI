import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Actor } from "./api/client";

const Session = createContext<{
  token: string;
  setToken: (token: string) => void;
  actor?: Actor;
  error: string;
  pending: boolean;
}>({ token: "", setToken: () => {}, error: "", pending: false });

export function SessionProvider({ children }: { children: ReactNode }) {
  const [token, update] = useState(sessionStorage.getItem("demo-token") || "");
  const cache = useQueryClient();
  const identity = useQuery({
    queryKey: ["identity", token],
    enabled: !!token,
    queryFn: () => api<Actor>("/api/v1/me", token),
    retry: false,
  });
  function setToken(value: string) {
    cache.clear();
    update(value);
    // Only synthetic local tokens persist across reload; OIDC credentials stay in memory.
    if (/^demo-(citizen(-2)?|reviewer|operator|admin)$/.test(value))
      sessionStorage.setItem("demo-token", value);
    else sessionStorage.removeItem("demo-token");
  }
  return (
    <Session.Provider
      value={{
        token,
        setToken,
        actor: identity.data,
        error: identity.error?.message || "",
        pending: !!token && identity.isPending,
      }}
    >
      {children}
    </Session.Provider>
  );
}

export const useSession = () => useContext(Session);

export function SignIn() {
  const { setToken, error, pending } = useSession();
  const [credential, setCredential] = useState("");
  const config = useQuery({
    queryKey: ["public-config"],
    queryFn: async () => {
      const response = await fetch("/api/v1/config/public");
      if (!response.ok) throw new Error("Pilot details unavailable");
      return response.json() as Promise<{ auth_provider?: string }>;
    },
  });
  return (
    <section className="panel">
      <h1>Sign in to the pilot</h1>
      {config.data?.auth_provider !== "oidc" && (
        <>
          <p>Use a pre-provisioned citizen for this local demo.</p>
          <div className="actions">
            <button onClick={() => setToken("demo-citizen")}>
              Continue as demo citizen
            </button>
            <button
              className="secondary"
              onClick={() => setToken("demo-citizen-2")}
            >
              Use second demo citizen
            </button>
          </div>
        </>
      )}
      <details>
        <summary>Use a provisioned identity token</summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setToken(credential);
            setCredential("");
          }}
        >
          <label htmlFor="identity-token">Identity token</label>
          <input
            id="identity-token"
            type="password"
            autoComplete="off"
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
            required
          />
          <button type="submit">Sign in with token</button>
        </form>
      </details>
      {pending && <p role="status">Checking your identity…</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
