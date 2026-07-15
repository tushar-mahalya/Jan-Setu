import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet, downloadWithAuth, ApiError } from "../api/client";
import type { GrievanceDetail } from "../api/types";
import StatusChip, { metaForStatus } from "../components/StatusChip";
import StatusTimeline from "../components/StatusTimeline";

export default function ComplaintDetail() {
  const { id } = useParams<{ id?: string }>();
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const query = useQuery({ queryKey: ["grievance", id], queryFn: () => apiGet<GrievanceDetail>(`/api/grievances/${id}`), enabled: Boolean(id) });
  const download = async () => {
    if (!query.data?.pdf_url) return;
    setDownloadError(null);
    setDownloading(true);
    try { await downloadWithAuth(query.data.pdf_url, `${query.data.human_id}.pdf`); }
    catch (error) { setDownloadError(error instanceof ApiError ? error.message : "Could not download the receipt. Please try again."); }
    finally { setDownloading(false); }
  };

  if (query.isLoading) return <div className="app-page detail-loading" role="status" aria-live="polite" aria-busy="true" aria-label="Loading complaint"><div className="detail-loading__header" /><div className="detail-loading__grid"><span /><span /></div></div>;
  if (query.isError) return <div className="app-page"><div className="app-notice app-notice--warning" role="alert"><strong>We couldn’t open this complaint.</strong><span>Check your connection, then try again. Your complaint remains safely filed.</span><button type="button" onClick={() => query.refetch()}>Try again</button></div></div>;
  if (!query.data) return null;

  const grievance = query.data;
  const current = metaForStatus(grievance.status);
  return <div className="app-page detail-page">
    <nav className="detail-breadcrumb" aria-label="Breadcrumb"><Link to="/dashboard">Your complaints</Link><span aria-hidden="true">/</span><span aria-current="page">{grievance.human_id}</span></nav>
    <header className="detail-header"><Link to="/dashboard" className="wizard-back" aria-label="Back to dashboard">‹</Link><div><span>{grievance.human_id}</span><h1>{grievance.category ?? "Your complaint"}</h1><p>Filed {new Date(grievance.created_at).toLocaleDateString(undefined, { dateStyle: "long" })}</p></div><StatusChip status={grievance.status} /></header>
    <div className="detail-current" role="status"><span aria-hidden="true">✓</span><div><strong>Current status: {current.label}</strong><p>{grievance.status === "submitted" ? "The responsible department has received your complaint." : "We’ll keep this page updated as your complaint moves forward."}</p></div></div>
    <div className="detail-layout"><article className="detail-summary"><h2>Complaint details</h2><dl><div><dt>Department</dt><dd>{grievance.department_key ?? "Finding the right department"}</dd></div><div><dt>Priority</dt><dd>{grievance.priority ?? "Standard"}</dd></div><div><dt>Filed through</dt><dd>{grievance.source === "whatsapp" ? "WhatsApp" : "Jan Setu web portal"}</dd></div><div><dt>Reports grouped</dt><dd>{grievance.report_count > 1 ? `${grievance.report_count} citizen reports` : "This report only"}</dd></div><div className="is-wide"><dt>Location</dt><dd>{grievance.address ?? "Location is being resolved"}</dd></div><div className="is-wide"><dt>Description</dt><dd>{grievance.issue_text ?? "No typed description was provided. Voice or photo evidence may be attached."}</dd></div></dl>{grievance.report_count > 1 && <p className="detail-reports"><b>{grievance.report_count}</b> citizens have reported this issue. Grouping nearby reports gives the department one clearer case to act on.</p>}{grievance.pdf_url && <div className="detail-download"><button type="button" className="app-button app-button--soft" onClick={download} disabled={downloading}>{downloading ? "Preparing receipt…" : "Download complaint receipt"}</button>{downloadError && <p className="app-error" role="alert">{downloadError}</p>}</div>}</article><aside className="detail-history"><h2>Status history</h2><p>Each update is recorded here.</p><StatusTimeline events={grievance.events} /></aside></div>
  </div>;
}
