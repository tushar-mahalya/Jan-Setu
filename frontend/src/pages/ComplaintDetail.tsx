import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet, downloadWithAuth, ApiError } from "../api/client";
import type { GrievanceDetail } from "../api/types";
import StatusChip, { metaForStatus } from "../components/StatusChip";
import StatusTimeline from "../components/StatusTimeline";
import { humanizeKey } from "../lib/text";
import { useI18n, fill } from "../i18n/I18nContext";

function languageLabel(language: string) {
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(language.split("-")[0]) ?? language; }
  catch { return language; }
}

export default function ComplaintDetail() {
  const { t, bcp47 } = useI18n();
  const { id } = useParams<{ id?: string }>();
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const query = useQuery({ queryKey: ["grievance", id], queryFn: () => apiGet<GrievanceDetail>(`/api/grievances/${id}`), enabled: Boolean(id) });
  const download = async () => {
    if (!query.data?.pdf_url) return;
    setDownloadError(null); setDownloading(true);
    try { await downloadWithAuth(query.data.pdf_url, `${query.data.human_id}.pdf`); }
    catch (error) { setDownloadError(error instanceof ApiError ? error.message : t.receiptDownloadError); }
    finally { setDownloading(false); }
  };

  if (query.isLoading) return <div className="app-page detail-loading" role="status" aria-live="polite" aria-busy="true" aria-label={t.loadingComplaint}><div className="detail-loading__header" /><div className="detail-loading__grid"><span /><span /></div></div>;
  if (query.isError) return <div className="app-page"><div className="app-notice app-notice--warning" role="alert"><strong>{t.detailErrorTitle}</strong><span>{t.detailErrorBody}</span><button type="button" onClick={() => query.refetch()}>{t.retry}</button></div></div>;
  if (!query.data) return null;

  const grievance = query.data;
  const current = metaForStatus(grievance.status);
  const facts = grievance.structured_facts;
  const summary = facts?.summary;
  const transcripts = grievance.transcript_metadata ?? [];
  const typedText = facts?.original_text || (!transcripts.length ? grievance.issue_text : undefined);

  return <div className="app-page detail-page">
    <nav className="detail-breadcrumb" aria-label="Breadcrumb"><Link to="/dashboard">{t.crumbComplaints}</Link><span aria-hidden="true">/</span><span aria-current="page">{grievance.human_id}</span></nav>
    <header className="detail-header"><Link to="/dashboard" className="wizard-back" aria-label={t.backToDashboardAria}>‹</Link><div><span>{grievance.human_id}</span><h1>{grievance.category_label ?? humanizeKey(grievance.category) ?? t.yourComplaint}</h1><p>{fill(t.filedOn, { date: new Date(grievance.created_at).toLocaleDateString(bcp47, { dateStyle: "long" }) })}</p></div><StatusChip status={grievance.status} /></header>
    <div className="detail-current" role="status"><span aria-hidden="true">✓</span><div><strong>{fill(t.currentStatus, { status: current.fallback ?? t[current.key] })}</strong><p>{grievance.status === "submitted" ? t.statusDeliveredNote : t.statusProgressNote}</p></div></div>
    <div className="detail-layout"><article className="detail-summary"><h2>{t.detailsTitle}</h2><dl>
      <div><dt>{t.dtServiceArea}</dt><dd>{grievance.domain_label ?? t.municipalServices}</dd></div>
      <div><dt>{t.dtDepartment}</dt><dd>{grievance.department_name ?? humanizeKey(grievance.department_key) ?? t.findingDepartment}</dd></div>
      <div><dt>{t.dtPriority}</dt><dd>{grievance.priority === "high" ? t.priorityHigh : t.priorityNormal}</dd></div>
      <div><dt>{t.dtHandling}</dt><dd>{grievance.disposition ? grievance.disposition.replace(/_/g, " ") : t.beingPrepared}</dd></div>
      <div><dt>{t.dtFiledThrough}</dt><dd>{grievance.source === "whatsapp" ? t.viaWhatsApp : t.viaWeb}</dd></div>
      <div><dt>{t.dtReports}</dt><dd>{grievance.report_count > 1 ? fill(t.reportsCount, { count: grievance.report_count }) : t.reportsOnlyThis}</dd></div>
      <div className="is-wide"><dt>{t.dtLocation}</dt><dd>{grievance.address ?? t.locationResolving}</dd></div>
      {summary && <div className="is-wide"><dt>{t.dtSummary}</dt><dd className="quote-block">{summary}</dd></div>}
      {typedText && <div className="is-wide"><dt>{t.dtWritten}</dt><dd>{typedText}</dd></div>}
      {transcripts.map((clip, index) => <div className="is-wide" key={`${clip.language}-${index}`}><dt>{fill(t.dtVoiceTranscript, { n: index + 1 })} <small>({languageLabel(clip.language)})</small></dt><dd>{clip.text}</dd></div>)}
      {!summary && !grievance.issue_text && <div className="is-wide"><dt>{t.dtDescription}</dt><dd>{t.noUsableDescription}</dd></div>}
      {facts?.requested_action && <div className="is-wide"><dt>{t.dtRequestedAction}</dt><dd>{facts.requested_action}</dd></div>}
      {facts?.landmark && <div><dt>{t.dtLandmark}</dt><dd>{facts.landmark}</dd></div>}
      {grievance.routing?.sla_hours != null && <div><dt>{t.dtSla}</dt><dd>{fill(t.slaHours, { count: grievance.routing.sla_hours })}</dd></div>}
    </dl>{grievance.report_count > 1 && <p className="detail-reports">{fill(t.groupedNote, { count: grievance.report_count })}</p>}{grievance.pdf_url && <div className="detail-download"><button type="button" className="app-button app-button--soft" onClick={download} disabled={downloading}>{downloading ? t.preparingReceipt : t.downloadReceipt}</button>{downloadError && <p className="app-error" role="alert">{downloadError}</p>}</div>}</article><aside className="detail-history"><h2>{t.historyTitle}</h2><p>{t.historyNote}</p><StatusTimeline events={grievance.events} /></aside></div>
  </div>;
}
