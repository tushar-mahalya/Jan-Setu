import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api/client";
import type { GrievanceSummary } from "../api/types";
import StatusChip from "../components/StatusChip";

function categoryLetter(category: string | null) {
  return (category || "?").trim().charAt(0).toUpperCase();
}

export default function Dashboard() {
  const query = useQuery({ queryKey: ["grievances"], queryFn: () => apiGet<GrievanceSummary[]>("/api/grievances?limit=20&offset=0") });
  return <div className="app-page dashboard-page">
    <header className="app-page__header"><div><span className="app-kicker">CITIZEN DASHBOARD</span><h1>Your complaints</h1><p>Every report, visible from registration to department action.</p></div><Link to="/complaints/new" className="app-button app-button--orange">＋ New complaint</Link></header>
    {query.isLoading && <div className="complaint-table is-loading" role="status" aria-live="polite" aria-label="Loading complaints" aria-busy="true"><span /><span /><span /></div>}
    {query.isError && <div className="app-notice app-notice--warning" role="alert"><strong>We couldn’t load your complaints.</strong><span>Check your connection, then try again. Your filed reports remain safe.</span><button type="button" onClick={() => query.refetch()}>Try again</button></div>}
    {query.data?.length === 0 && <div className="app-empty"><div className="app-empty__illustration" aria-hidden="true"><span>⌖</span><i /><b /></div><h2>Your neighbourhood starts here</h2><p>Report a local issue with a location, voice note, text, or photo. We’ll route it and give you a ticket to track.</p><Link to="/complaints/new" className="app-button app-button--orange">File your first complaint</Link></div>}
    {query.data && query.data.length > 0 && <div className="complaint-table" role="table" aria-label="Your complaints"><div className="complaint-table__head" role="row"><span role="columnheader">Ticket ID</span><span role="columnheader">Category</span><span role="columnheader">Status</span><span role="columnheader">Filed on</span></div>{query.data.map((item, index) => <Link key={item.id} to={`/complaints/${item.id}`} className="complaint-table__row" style={{ "--row-delay": `${Math.min(index, 8) * 35}ms` } as CSSProperties} role="row" aria-label={`Open complaint ${item.human_id}, ${item.category ?? "category pending"}`}><strong role="cell">{item.human_id}</strong><span className="complaint-category" role="cell"><i aria-hidden="true">{categoryLetter(item.category)}</i><span><b>{item.category ?? "Category pending"}</b><small>{item.priority ? `${item.priority} priority` : "Municipal routing"}</small></span></span><span role="cell"><StatusChip status={item.status} /></span><time role="cell" dateTime={item.created_at}>{new Date(item.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</time></Link>)}</div>}
  </div>;
}
