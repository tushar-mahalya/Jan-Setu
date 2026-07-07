import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { AuthStatusResponse, RequestCodeResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export default function Login() {
  const navigate = useNavigate();
  const auth = useAuth();
  const [phone, setPhone] = useState("");
  const [verification, setVerification] = useState<RequestCodeResponse | null>(null);

  const requestCode = useMutation({
    mutationFn: (phoneNumber: string) =>
      apiPostJson<RequestCodeResponse>("/auth/request-code", { phone: phoneNumber }, { auth: false }),
    onSuccess: (data) => setVerification(data),
  });

  const statusQuery = useQuery({
    queryKey: ["auth-status", verification?.verification_id],
    queryFn: () =>
      apiGet<AuthStatusResponse>(
        `/auth/status?verification_id=${encodeURIComponent(verification!.verification_id)}`,
        { auth: false },
      ),
    enabled: Boolean(verification),
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 2500 : false),
  });

  useEffect(() => {
    const status = statusQuery.data;
    if (status?.status === "verified" && status.access_token) {
      auth.login(status.access_token);
      navigate("/dashboard", { replace: true });
    }
  }, [statusQuery.data, auth, navigate]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!phone.trim()) return;
    requestCode.mutate(phone.trim());
  };

  const handleRequestNewCode = () => {
    setVerification(null);
    requestCode.reset();
  };

  const isExpired = statusQuery.data?.status === "expired";
  const isVerified = statusQuery.data?.status === "verified";

  return (
    <main className="auth-page">
      <div className="auth-card">
        <span className="eyebrow">Jan-Setu Citizen Portal</span>
        <h1>Sign in with your phone</h1>

        {!verification && (
          <form className="form" onSubmit={handleSubmit}>
            <label className="field">
              <span className="field__label">01 — Phone number</span>
              <input
                type="tel"
                inputMode="tel"
                placeholder="+91 98765 43210"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                required
              />
              <span className="field__hint">Use international format, e.g. +91XXXXXXXXXX</span>
            </label>
            {requestCode.isError && (
              <p className="field-error">
                {requestCode.error instanceof ApiError ? requestCode.error.message : "Something went wrong."}
              </p>
            )}
            <button type="submit" className="btn btn--primary" disabled={requestCode.isPending}>
              {requestCode.isPending ? "Requesting…" : "Get verification code"}
            </button>
          </form>
        )}

        {verification && !isExpired && (
          <div className="verification-panel">
            <p>Send this code to our WhatsApp number to verify your phone.</p>
            <p className="verification-code mono">{verification.code}</p>
            <a className="btn btn--secondary" href={verification.wa_link} target="_blank" rel="noreferrer">
              Open WhatsApp
            </a>
            <p className="verification-panel__status" data-state={isVerified ? "verified" : undefined} aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              {isVerified ? "Verified — redirecting…" : "Waiting for confirmation…"}
            </p>
          </div>
        )}

        {isExpired && (
          <div className="verification-panel">
            <p>This code has expired.</p>
            <button type="button" className="btn btn--primary" onClick={handleRequestNewCode}>
              Request a new code
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
