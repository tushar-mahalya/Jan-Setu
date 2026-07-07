import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet, downloadWithAuth, ApiError } from "../api/client";
import type { GrievanceDetail } from "../api/types";
import StatusChip from "../components/StatusChip";
import StatusTimeline from "../components/StatusTimeline";

export default function ComplaintDetail() {
  const { id } = useParams<{ id: string }>();
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["grievance", id],
    queryFn: () => apiGet<GrievanceDetail>(`/api/grievances/${id}`),
    enabled: Boolean(id),
  });

  const handleDownload = async () => {
    if (!detailQuery.data?.pdf_url) return;
    setDownloadError(null);
    setIsDownloading(true);
    try {
      await downloadWithAuth(detailQuery.data.pdf_url, `${detailQuery.data.human_id}.pdf`);
    } catch (error) {
      setDownloadError(error instanceof ApiError ? error.message : "Could not download the PDF.");
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <main className="page page--narrow">
      <p>
        <Link to="/dashboard" className="btn-link">
          ← Back to Dashboard
        </Link>
      </p>

      {detailQuery.isLoading && <p className="muted-note">Loading complaint…</p>}
      {detailQuery.isError && <p className="field-error">Could not load this complaint.</p>}

      {detailQuery.data && (
        <>
          <header className="page__header">
            <div>
              <p className="eyebrow mono">{detailQuery.data.human_id}</p>
              <h1>{detailQuery.data.category ?? "Uncategorized complaint"}</h1>
            </div>
            <StatusChip status={detailQuery.data.status} />
          </header>

          <dl className="review-card__grid">
            <div className="review-card__field">
              <dt>Department</dt>
              <dd>{detailQuery.data.department_key ?? "—"}</dd>
            </div>
            <div className="review-card__field">
              <dt>Priority</dt>
              <dd>{detailQuery.data.priority ?? "—"}</dd>
            </div>
            <div className="review-card__field">
              <dt>Term</dt>
              <dd>{detailQuery.data.term ?? "—"}</dd>
            </div>
            <div className="review-card__field">
              <dt>Source</dt>
              <dd>{detailQuery.data.source}</dd>
            </div>
            <div className="review-card__field review-card__field--wide">
              <dt>Address</dt>
              <dd>{detailQuery.data.address ?? "—"}</dd>
            </div>
            <div className="review-card__field review-card__field--wide">
              <dt>Description</dt>
              <dd>{detailQuery.data.issue_text ?? "—"}</dd>
            </div>
          </dl>

          {detailQuery.data.report_count > 1 && (
            <p className="muted-note">{detailQuery.data.report_count} people have reported this issue.</p>
          )}

          <section className="form-section">
            <h2 className="form-section__title">Status History</h2>
            <StatusTimeline events={detailQuery.data.events} />
          </section>

          {detailQuery.data.pdf_url && (
            <div className="form-actions">
              <button type="button" className="btn btn--secondary" onClick={handleDownload} disabled={isDownloading}>
                {isDownloading ? "Downloading…" : "Download PDF"}
              </button>
              {downloadError && <p className="field-error">{downloadError}</p>}
            </div>
          )}
        </>
      )}
    </main>
  );
}
