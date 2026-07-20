import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { apiPostJson } from "../api/client";

interface Requested { challenge_id: string; dev_code?: string | null }
interface Session { access_token: string; official: { name: string; role: string; jurisdiction_id: string } }

export function officialToken() { return sessionStorage.getItem("jan-setu-official-token"); }

export default function OfficialLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("demo-official@example.com");
  const [challenge, setChallenge] = useState<Requested | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (officialToken()) return <Navigate to="/official" replace />;
  const requestCode = async () => {
    setBusy(true); setError(null);
    try { setChallenge(await apiPostJson<Requested>("/api/official/auth/request-code", { email }, { auth: false })); }
    catch (value) { setError(value instanceof Error ? value.message : "Could not request code"); }
    finally { setBusy(false); }
  };
  const verify = async () => {
    if (!challenge) return;
    setBusy(true); setError(null);
    try {
      const result = await apiPostJson<Session>("/api/official/auth/verify", { challenge_id: challenge.challenge_id, code }, { auth: false });
      sessionStorage.setItem("jan-setu-official-token", result.access_token);
      sessionStorage.setItem("jan-setu-official-profile", JSON.stringify(result.official));
      navigate("/official", { replace: true });
    } catch (value) { setError(value instanceof Error ? value.message : "Invalid code"); }
    finally { setBusy(false); }
  };
  return <main className="official-login" id="main-content"><section className="official-login__panel"><span className="filed-stamp">Restricted government access</span><h1>Official operations</h1><p>Sign in with a pre-approved government email. Access and evidence views are audited.</p>{!challenge ? <><label>Official email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" /></label><button className="app-button app-button--teal" type="button" onClick={requestCode} disabled={busy || !email}>{busy ? "Requesting…" : "Send one-time code"}</button></> : <><label>One-time code<input value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={12} /></label>{challenge.dev_code && <p className="notice" role="status">Development code: <strong className="mono">{challenge.dev_code}</strong></p>}<button className="app-button app-button--teal" type="button" onClick={verify} disabled={busy || code.length < 6}>{busy ? "Verifying…" : "Open operations console"}</button><button className="btn-link" type="button" onClick={() => { setChallenge(null); setCode(""); }}>Use another email</button></>}{error && <p className="app-error" role="alert">{error}</p>}</section></main>;
}
