import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet, apiPostEmpty } from "../api/client";
import type { GrievanceSummary } from "../api/types";
import StatusChip from "../components/StatusChip";
import { useAuth } from "../auth/AuthContext";

export default function Dashboard() {
  const navigate = useNavigate();
  const auth = useAuth();

  const grievancesQuery = useQuery({
    queryKey: ["grievances"],
    queryFn: () => apiGet<GrievanceSummary[]>("/api/grievances?limit=20&offset=0"),
  });

  const handleLogout = async () => {
    try {
      await apiPostEmpty("/auth/logout");
    } finally {
      auth.logout();
      navigate("/login", { replace: true });
    }
  };

  return (
    <main className="page">
      <header className="page__header">
        <div>
          <span className="eyebrow">Jan-Setu Citizen Portal</span>
          <h1>Your Complaints</h1>
        </div>
        <div className="page__header-actions">
          <Link to="/complaints/new" className="btn btn--primary">
            + New Complaint
          </Link>
          <button type="button" className="btn-link" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      {grievancesQuery.isLoading && (
        <div className="complaint-list">
          <div className="skeleton-row" />
          <div className="skeleton-row" />
          <div className="skeleton-row" />
        </div>
      )}

      {grievancesQuery.isError && <p className="field-error">Could not load your complaints. Try refreshing.</p>}

      {grievancesQuery.data && grievancesQuery.data.length === 0 && (
        <p className="empty-state">No complaints yet. File your first one above.</p>
      )}

      {grievancesQuery.data && grievancesQuery.data.length > 0 && (
        <ul className="complaint-list">
          {grievancesQuery.data.map((item) => (
            <li key={item.id}>
              <Link to={`/complaints/${item.id}`} className="complaint-row">
                <span className="complaint-row__id mono">{item.human_id}</span>
                <span className="complaint-row__category">{item.category ?? "Uncategorized"}</span>
                <StatusChip status={item.status} />
                <span className="complaint-row__date">
                  {new Date(item.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
