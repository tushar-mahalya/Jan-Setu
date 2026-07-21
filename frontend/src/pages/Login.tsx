import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { AuthStatusResponse, RequestCodeResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useI18n, fill } from "../i18n/I18nContext";

function LoginArtwork() {
  const { t } = useI18n();
  return <svg className="login-artwork-svg" viewBox="0 0 440 260" role="img" aria-labelledby="login-art-title login-art-desc"><title id="login-art-title">{t.loginArtTitle}</title><desc id="login-art-desc">{t.loginArtDesc}</desc><path className="login-artwork-svg__ground" d="M52 218c65 20 253 23 337-1" /><circle className="login-artwork-svg__sun" cx="66" cy="51" r="28" /><path className="login-artwork-svg__building" d="M292 78h90v136h-90zM307 101h18v18h-18zM348 101h18v18h-18zM307 137h18v18h-18zM348 137h18v18h-18zM322 181h29v33h-29z" /><g className="login-artwork-svg__person"><circle cx="104" cy="123" r="24" /><path d="M65 215c3-48 18-70 39-70s36 22 39 70" /><path d="m133 167 52 26" /></g><g className="login-artwork-svg__phone"><rect x="170" y="59" width="88" height="161" rx="20" /><rect x="181" y="78" width="66" height="112" rx="8" /><path d="M205 204h18" /></g><g className="login-artwork-svg__message"><path d="M197 96h34a8 8 0 0 1 8 8v19a8 8 0 0 1-8 8h-17l-9 9v-9h-8a8 8 0 0 1-8-8v-19a8 8 0 0 1 8-8z" /><path d="m199 113 7 7 19-19" /></g><g className="login-artwork-svg__pin"><path d="M278 32c19 0 32 14 32 31 0 22-32 49-32 49s-32-27-32-49c0-17 13-31 32-31z" /><circle cx="278" cy="63" r="10" /></g><g className="login-artwork-svg__ticket"><rect x="272" y="147" width="115" height="62" rx="13" /><path d="M289 166h55M289 180h39" /><circle cx="367" cy="178" r="10" /><path d="m362 178 4 4 7-8" /></g></svg>;
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
  const { t, bcp47 } = useI18n();
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

  return <main className="login-screen"><section className="login-story"><Link className="login-story__about" to="/about">{t.loginHowLink}</Link><Link className="login-story__official" to="/official/login">{t.loginOfficialLink}</Link><div className="login-story__brand"><img src="/jan-setu-logo-dark.svg" alt="" aria-hidden="true" />{t.brand}</div><p>{t.tagline}</p><LoginArtwork /><div className="login-story__promise"><b>{t.loginPromiseTitle}</b><span>{t.loginPromiseBody}</span></div></section><section className="login-form-panel" aria-labelledby="sign-in-title">
    {!verification && <form className="login-form" onSubmit={submit}><div><span className="app-kicker">{t.loginKicker}</span><h1 id="sign-in-title">{t.loginTitle}</h1><p>{t.loginIntro}</p></div><label htmlFor="phone">{t.loginPhoneLabel}</label><input id="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" value={phone} onChange={(event) => setPhone(event.target.value)} required aria-describedby="phone-guidance" /><small id="phone-guidance">{t.loginPhoneHint}</small><ol className="login-steps" aria-label={t.loginStepsAria}><li><span>1</span>{t.loginStep1}</li><li><span>2</span>{t.loginStep2}</li><li><span>3</span>{t.loginStep3}</li></ol>{requestCode.isError && <p className="app-error" role="alert">{requestCode.error instanceof ApiError ? requestCode.error.message : t.loginError}</p>}<button className="app-button app-button--orange" disabled={requestCode.isPending}>{requestCode.isPending ? t.loginSubmitBusy : t.loginSubmit}</button><p className="login-privacy">{t.loginPrivacy}</p></form>}
    {verification?.method === "whatsapp_approval" && !expired && !denied && <section className="login-form otp-panel login-approval-panel" aria-live="polite"><div><span className="app-kicker">{t.approvalKicker}</span><h1>{t.approvalTitle}</h1><p>{t.approvalBody}</p></div><div className="login-approval-device"><span aria-hidden="true">✓</span><div><strong>{verification.browser_label ?? t.approvalDeviceFallback}</strong><small>{verification.expires_at ? fill(t.approvalExpiresAt, { time: new Date(verification.expires_at).toLocaleTimeString(bcp47, { hour: "2-digit", minute: "2-digit" }) }) : t.approvalExpiresSoon}</small></div></div><button type="button" className="otp-change-number" onClick={reset}>{t.useAnotherNumber}</button><div className={verified ? "otp-status is-verified" : "otp-status"} role="status"><span />{verified ? t.approvalVerified : t.approvalWaiting}</div>{approvalQuery.isError && <p className="app-error" role="alert">{t.approvalPollError}</p>}</section>}
    {verification?.method === "reverse_code" && !expired && <section className="login-form otp-panel" aria-live="polite"><div><span className="app-kicker">{t.codeKicker}</span><h1>{t.codeTitle}</h1><p>{t.codeBody}</p></div><div className="otp-code" aria-label={fill(t.codeAria, { code: verification.code ?? "" })}>{verification.code}</div>{verification.wa_link && <a className="app-button app-button--orange" href={verification.wa_link} target="_blank" rel="noreferrer">{t.codeOpen}</a>}<button type="button" className="otp-change-number" onClick={reset}>{t.useAnotherNumber}</button><div className={verified ? "otp-status is-verified" : "otp-status"} role="status"><span />{verified ? t.codeVerified : t.codeWaiting}</div></section>}
    {denied && <section className="login-form"><div><span className="app-kicker">{t.deniedKicker}</span><h1>{t.deniedTitle}</h1><p>{t.deniedBody}</p></div><button type="button" className="app-button app-button--orange" onClick={reset}>{t.retry}</button></section>}
    {expired && <section className="login-form"><div><span className="app-kicker">{t.expiredKicker}</span><h1>{t.expiredTitle}</h1><p>{t.expiredBody}</p></div><button type="button" className="app-button app-button--orange" onClick={reset}>{t.expiredCta}</button></section>}
  </section></main>;
}
