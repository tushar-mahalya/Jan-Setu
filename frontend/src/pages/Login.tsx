import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { AuthStatusResponse, RequestCodeResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";

function LoginArtwork() {
  return <svg className="login-artwork-svg" viewBox="0 0 440 260" role="img" aria-labelledby="login-art-title login-art-desc">
    <title id="login-art-title">A citizen reports a neighbourhood issue on WhatsApp</title>
    <desc id="login-art-desc">A citizen, phone, location pin and confirmed complaint ticket connected in one simple flow.</desc>
    <path className="login-artwork-svg__ground" d="M52 218c65 20 253 23 337-1" />
    <circle className="login-artwork-svg__sun" cx="66" cy="51" r="28" />
    <path className="login-artwork-svg__building" d="M292 78h90v136h-90zM307 101h18v18h-18zM348 101h18v18h-18zM307 137h18v18h-18zM348 137h18v18h-18zM322 181h29v33h-29z" />
    <g className="login-artwork-svg__person"><circle cx="104" cy="123" r="24" /><path d="M65 215c3-48 18-70 39-70s36 22 39 70" /><path d="m133 167 52 26" /></g>
    <g className="login-artwork-svg__phone"><rect x="170" y="59" width="88" height="161" rx="20" /><rect x="181" y="78" width="66" height="112" rx="8" /><path d="M205 204h18" /></g>
    <g className="login-artwork-svg__message"><path d="M197 96h34a8 8 0 0 1 8 8v19a8 8 0 0 1-8 8h-17l-9 9v-9h-8a8 8 0 0 1-8-8v-19a8 8 0 0 1 8-8z" /><circle cx="204" cy="113" r="2.4" /><circle cx="214" cy="113" r="2.4" /><circle cx="224" cy="113" r="2.4" /></g>
    <g className="login-artwork-svg__pin"><path d="M278 32c19 0 32 14 32 31 0 22-32 49-32 49s-32-27-32-49c0-17 13-31 32-31z" /><circle cx="278" cy="63" r="10" /></g>
    <g className="login-artwork-svg__ticket"><rect x="272" y="147" width="115" height="62" rx="13" /><path d="M289 166h55M289 180h39" /><circle cx="367" cy="178" r="10" /><path d="m362 178 4 4 7-8" /></g>
  </svg>;
}

export default function Login() {
  const navigate = useNavigate();
  const auth = useAuth();
  const [phone, setPhone] = useState("");
  const [verification, setVerification] = useState<RequestCodeResponse | null>(null);
  const requestCode = useMutation({ mutationFn: (value: string) => apiPostJson<RequestCodeResponse>("/auth/request-code", { phone: value }, { auth: false }), onSuccess: setVerification });
  const statusQuery = useQuery({
    queryKey: ["auth-status", verification?.verification_id],
    queryFn: () => apiGet<AuthStatusResponse>(`/auth/status?verification_id=${encodeURIComponent(verification!.verification_id)}`, { auth: false }),
    enabled: Boolean(verification),
    // Keep polling through transient failures until verification reaches a terminal state.
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return verification && status !== "verified" && status !== "expired" ? 2500 : false;
    },
  });
  useEffect(() => {
    const status = statusQuery.data;
    if (status?.status === "verified" && status.access_token) {
      auth.login(status.access_token);
      navigate("/dashboard", { replace: true });
    }
  }, [statusQuery.data, auth, navigate]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (phone.trim()) requestCode.mutate(phone.trim());
  };
  const expired = statusQuery.data?.status === "expired";
  const verified = statusQuery.data?.status === "verified";

  return <main className="login-screen">
    <section className="login-story">
      <Link className="login-story__about" to="/about">How Jan Setu works →</Link>
      <div className="login-story__brand"><span /> Jan Setu</div>
      <p>Citizen grievance portal<br /><span lang="hi">नागरिक शिकायत पोर्टल</span></p>
      <LoginArtwork />
      <div className="login-story__promise"><b>Report simply. Track visibly.</b><span>Use location, voice, text, or a photo. Every filed complaint gets a ticket and status history.</span></div>
    </section>
    <section className="login-form-panel" aria-labelledby="sign-in-title">
      {!verification && <form className="login-form" onSubmit={submit}>
        <div><span className="app-kicker">Citizen sign in</span><h1 id="sign-in-title">Use your WhatsApp number</h1><p>Jan Setu will show you a one-time code. Send that code to our WhatsApp bot to confirm it’s you—no password required.</p></div>
        <label htmlFor="phone">WhatsApp phone number <span lang="hi">/ फ़ोन नंबर</span></label>
        <input id="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" value={phone} onChange={(event) => setPhone(event.target.value)} required aria-describedby="phone-guidance" />
        <small id="phone-guidance">Use international format and the same number you will message from.</small>
        <ol className="login-steps" aria-label="Sign-in steps"><li><span>1</span>Get your code</li><li><span>2</span>Send it on WhatsApp</li><li><span>3</span>Return here automatically</li></ol>
        {requestCode.isError && <p className="app-error" role="alert">{requestCode.error instanceof ApiError ? requestCode.error.message : "Could not create a code. Your number has not been submitted—please try again."}</p>}
        <button className="app-button app-button--orange" disabled={requestCode.isPending}>{requestCode.isPending ? "Creating your code…" : "Get verification code →"}</button>
        <p className="login-privacy">We store your phone number only to identify your reports and send complaint updates.</p>
      </form>}
      {verification && !expired && <section className="login-form otp-panel" aria-live="polite">
        <div><span className="app-kicker">WhatsApp verification</span><h1>Send this exact code</h1><p>Tap the button below. WhatsApp opens with your one-time code ready to send to Jan Setu.</p></div>
        <div className="otp-code" aria-label={`Verification code ${verification.code}`}>{verification.code}</div>
        <a className="app-button app-button--orange" href={verification.wa_link} target="_blank" rel="noreferrer">Open WhatsApp and send →</a>
        <button type="button" className="otp-change-number" onClick={() => { setVerification(null); requestCode.reset(); }}>Use a different number</button>
        <div className={verified ? "otp-status is-verified" : "otp-status"} role="status"><span />{verified ? "Verified — opening your dashboard…" : "Waiting securely for your WhatsApp message…"}</div>
        {statusQuery.isError && <p className="app-error" role="alert">We couldn’t check confirmation just now. Keep this page open; Jan Setu will retry automatically.</p>}
      </section>}
      {expired && <section className="login-form"><div><span className="app-kicker">Code expired</span><h1>Let’s create a fresh code</h1><p>Codes expire after ten minutes to protect your account. You can request another immediately.</p></div><button type="button" className="app-button app-button--orange" onClick={() => { setVerification(null); requestCode.reset(); }}>Request a new code</button></section>}
    </section>
  </main>;
}
