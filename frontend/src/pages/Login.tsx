import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { AuthStatusResponse, RequestCodeResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";

function LoginArtwork() {
  return <svg className="login-artwork-svg" viewBox="0 0 440 260" role="img" aria-labelledby="login-art-title login-art-desc"><title id="login-art-title">A citizen approves Jan Setu sign-in on WhatsApp</title><desc id="login-art-desc">A citizen, phone, confirmation buttons and tracked complaint ticket connected in one secure flow.</desc><path className="login-artwork-svg__ground" d="M52 218c65 20 253 23 337-1" /><circle className="login-artwork-svg__sun" cx="66" cy="51" r="28" /><path className="login-artwork-svg__building" d="M292 78h90v136h-90zM307 101h18v18h-18zM348 101h18v18h-18zM307 137h18v18h-18zM348 137h18v18h-18zM322 181h29v33h-29z" /><g className="login-artwork-svg__person"><circle cx="104" cy="123" r="24" /><path d="M65 215c3-48 18-70 39-70s36 22 39 70" /><path d="m133 167 52 26" /></g><g className="login-artwork-svg__phone"><rect x="170" y="59" width="88" height="161" rx="20" /><rect x="181" y="78" width="66" height="112" rx="8" /><path d="M205 204h18" /></g><g className="login-artwork-svg__message"><path d="M197 96h34a8 8 0 0 1 8 8v19a8 8 0 0 1-8 8h-17l-9 9v-9h-8a8 8 0 0 1-8-8v-19a8 8 0 0 1 8-8z" /><path d="m199 113 7 7 19-19" /></g><g className="login-artwork-svg__pin"><path d="M278 32c19 0 32 14 32 31 0 22-32 49-32 49s-32-27-32-49c0-17 13-31 32-31z" /><circle cx="278" cy="63" r="10" /></g><g className="login-artwork-svg__ticket"><rect x="272" y="147" width="115" height="62" rx="13" /><path d="M289 166h55M289 180h39" /><circle cx="367" cy="178" r="10" /><path d="m362 178 4 4 7-8" /></g></svg>;
}

function randomNonce() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function browserLabel() {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS/.test(ua) ? "macOS" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "device";
  return `${browser} on ${os}`;
}

export default function Login() {
  const navigate = useNavigate();
  const auth = useAuth();
  const [phone, setPhone] = useState("");
  const [verification, setVerification] = useState<RequestCodeResponse | null>(null);
  const nonceRef = useRef("");
  const requestCode = useMutation({
    mutationFn: (value: string) => {
      nonceRef.current = randomNonce();
      return apiPostJson<RequestCodeResponse>("/auth/request-code", { phone: value, browser_nonce: nonceRef.current, browser_label: browserLabel() }, { auth: false });
    },
    onSuccess: setVerification,
  });
  const approvalQuery = useQuery({
    queryKey: ["approval-status", verification?.verification_id],
    queryFn: () => apiPostJson<AuthStatusResponse>("/auth/approval-status", { verification_id: verification!.verification_id, browser_nonce: nonceRef.current }, { auth: false }),
    enabled: verification?.method === "whatsapp_approval",
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const current = query.state.data?.status;
      return verification?.method === "whatsapp_approval" && current !== "verified" && current !== "denied" && current !== "expired" ? 2500 : false;
    },
  });
  const codeQuery = useQuery({
    queryKey: ["auth-status", verification?.verification_id],
    queryFn: () => apiGet<AuthStatusResponse>(`/auth/status?verification_id=${encodeURIComponent(verification!.verification_id)}`, { auth: false }),
    enabled: verification?.method === "reverse_code",
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const current = query.state.data?.status;
      return verification?.method === "reverse_code" && current !== "verified" && current !== "expired" ? 2500 : false;
    },
  });
  const authStatus = verification?.method === "whatsapp_approval" ? approvalQuery.data : codeQuery.data;
  useEffect(() => {
    if (authStatus?.status === "verified" && authStatus.access_token) {
      auth.login(authStatus.access_token);
      navigate("/dashboard", { replace: true });
    }
  }, [authStatus, auth, navigate]);
  const reset = () => { setVerification(null); nonceRef.current = ""; requestCode.reset(); };
  const submit = (event: FormEvent) => { event.preventDefault(); if (phone.trim()) requestCode.mutate(phone.trim()); };
  const expired = authStatus?.status === "expired";
  const denied = authStatus?.status === "denied";
  const verified = authStatus?.status === "verified";

  return <main className="login-screen"><section className="login-story"><Link className="login-story__about" to="/about">How Jan Setu works →</Link><div className="login-story__brand"><span /> Jan Setu</div><p>Citizen grievance portal<br /><span lang="hi">नागरिक शिकायत पोर्टल</span></p><LoginArtwork /><div className="login-story__promise"><b>Approve securely. Track visibly.</b><span>Existing users approve sign-in in WhatsApp. New users verify once with a secure code.</span></div></section><section className="login-form-panel" aria-labelledby="sign-in-title">
    {!verification && <form className="login-form" onSubmit={submit}><div><span className="app-kicker">Citizen sign in</span><h1 id="sign-in-title">Use your WhatsApp number</h1><p>If your account is already linked, Jan Setu sends a WhatsApp notification. Tap Yes to approve this browser—no code to type.</p></div><label htmlFor="phone">WhatsApp phone number <span lang="hi">/ फ़ोन नंबर</span></label><input id="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" value={phone} onChange={(event) => setPhone(event.target.value)} required aria-describedby="phone-guidance" /><small id="phone-guidance">Use the number linked to your Jan Setu WhatsApp account.</small><ol className="login-steps" aria-label="Sign-in steps"><li><span>1</span>Enter your number</li><li><span>2</span>Approve on WhatsApp</li><li><span>3</span>Dashboard opens</li></ol>{requestCode.isError && <p className="app-error" role="alert">{requestCode.error instanceof ApiError ? requestCode.error.message : "Could not start sign-in. Please try again."}</p>}<button className="app-button app-button--orange" disabled={requestCode.isPending}>{requestCode.isPending ? "Checking securely…" : "Continue securely →"}</button><p className="login-privacy">We never ask you to share a WhatsApp OTP with another person.</p></form>}
    {verification?.method === "whatsapp_approval" && !expired && !denied && <section className="login-form otp-panel login-approval-panel" aria-live="polite"><div><span className="app-kicker">Approve on WhatsApp</span><h1>Check your Jan Setu chat</h1><p>We sent a sign-in request with <strong>Yes, it’s me</strong> and <strong>No, deny</strong> buttons.</p></div><div className="login-approval-device"><span aria-hidden="true">✓</span><div><strong>{verification.browser_label ?? "This browser"}</strong><small>Request expires {verification.expires_at ? new Date(verification.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "soon"}</small></div></div><button type="button" className="otp-change-number" onClick={reset}>Use a different number</button><div className={verified ? "otp-status is-verified" : "otp-status"} role="status"><span />{verified ? "Approved — opening your dashboard…" : "Waiting securely for your approval…"}</div>{approvalQuery.isError && <p className="app-error" role="alert">Could not check approval just now. Keep this page open; Jan Setu will retry.</p>}</section>}
    {verification?.method === "reverse_code" && !expired && <section className="login-form otp-panel" aria-live="polite"><div><span className="app-kicker">WhatsApp verification</span><h1>Send this exact code</h1><p>This number needs code verification, or WhatsApp’s approval window is closed. Tap below to send the code to Jan Setu.</p></div><div className="otp-code" aria-label={`Verification code ${verification.code}`}>{verification.code}</div>{verification.wa_link && <a className="app-button app-button--orange" href={verification.wa_link} target="_blank" rel="noreferrer">Open WhatsApp and send →</a>}<button type="button" className="otp-change-number" onClick={reset}>Use a different number</button><div className={verified ? "otp-status is-verified" : "otp-status"} role="status"><span />{verified ? "Verified — opening your dashboard…" : "Waiting securely for your WhatsApp message…"}</div></section>}
    {denied && <section className="login-form"><div><span className="app-kicker">Sign-in denied</span><h1>Your account remains protected</h1><p>The WhatsApp request was denied. If that was you, start a fresh sign-in. If not, no action is needed.</p></div><button type="button" className="app-button app-button--orange" onClick={reset}>Try again</button></section>}
    {expired && <section className="login-form"><div><span className="app-kicker">Request expired</span><h1>Let’s start securely again</h1><p>Sign-in requests expire after ten minutes and can only be used once.</p></div><button type="button" className="app-button app-button--orange" onClick={reset}>Start a new request</button></section>}
  </section></main>;
}
