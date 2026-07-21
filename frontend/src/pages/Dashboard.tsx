import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api/client";
import type { GrievanceSummary } from "../api/types";
import StatusChip from "../components/StatusChip";
import { humanizeKey } from "../lib/text";
import { useI18n, fill } from "../i18n/I18nContext";

function categoryLetter(category: string | null) {
  return (category || "?").trim().charAt(0).toUpperCase();
}

export default function Dashboard() {
  const { t, bcp47 } = useI18n();
  const query = useQuery({ queryKey: ["grievances"], queryFn: () => apiGet<GrievanceSummary[]>("/api/grievances?limit=20&offset=0") });
  return <div className="app-page dashboard-page">
    <header className="app-page__header"><div><span className="app-kicker">{t.dashKicker}</span><h1>{t.dashTitle}</h1><p>{t.dashSub}</p></div><Link to="/complaints/new" className="app-button app-button--orange">{t.newComplaintCta}</Link></header>
    {query.isLoading && <div className="complaint-table is-loading" role="status" aria-live="polite" aria-label={t.dashLoadingAria} aria-busy="true"><span /><span /><span /></div>}
    {query.isError && <div className="app-notice app-notice--warning" role="alert"><strong>{t.dashErrorTitle}</strong><span>{t.dashErrorBody}</span><button type="button" onClick={() => query.refetch()}>{t.retry}</button></div>}
    {query.data?.length === 0 && <div className="app-empty"><div className="app-empty__illustration" aria-hidden="true"><span>⌖</span><i /><b /></div><h2>{t.emptyTitle}</h2><p>{t.emptyBody}</p><Link to="/complaints/new" className="app-button app-button--orange">{t.emptyCta}</Link></div>}
    {query.data && query.data.length > 0 && <div className="complaint-table" role="table" aria-label={t.tableAria}><div className="complaint-table__head" role="row"><span role="columnheader">{t.thTicket}</span><span role="columnheader">{t.thCategory}</span><span role="columnheader">{t.thStatus}</span><span role="columnheader">{t.thFiled}</span></div>{query.data.map((item, index) => <Link key={item.id} to={`/complaints/${item.id}`} className="complaint-table__row" style={{ "--row-delay": `${Math.min(index, 8) * 35}ms` } as CSSProperties} role="row" aria-label={fill(t.openComplaintAria, { id: item.human_id })}><strong role="cell">{item.human_id}</strong><span className="complaint-category" role="cell"><i aria-hidden="true">{categoryLetter(item.category)}</i><span><b>{humanizeKey(item.category) ?? t.categoryPending}</b><small>{item.priority === "high" ? t.priorityHigh : item.priority ? t.priorityNormal : t.municipalRouting}</small></span></span><span role="cell"><StatusChip status={item.status} /></span><time role="cell" dateTime={item.created_at}>{new Date(item.created_at).toLocaleDateString(bcp47, { day: "numeric", month: "short", year: "numeric" })}</time></Link>)}</div>}
  </div>;
}
