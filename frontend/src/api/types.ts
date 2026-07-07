// TypeScript interfaces mirroring the Jan-Setu backend Pydantic schemas.

export type ImageMatchStatus = "none" | "matched" | "mismatched" | "skipped";

export type GrievanceStatus =
  | "draft"
  | "processing"
  | "awaiting_confirmation"
  | "photo_mismatch"
  | "registered"
  | "pending_window"
  | "dispatching"
  | "submitted"
  | "duplicate"
  | "cancelled"
  | "dispatch_failed";

export type GrievanceSource = "whatsapp" | "web";

export interface RequestCodeResponse {
  verification_id: string;
  code: string;
  wa_link: string;
}

export type AuthStatusValue = "pending" | "verified" | "expired";

export interface AuthStatusResponse {
  status: AuthStatusValue;
  access_token?: string;
}

export interface RefreshResponse {
  access_token: string;
}

export interface LogoutResponse {
  status: string;
}

export interface GrievanceDraftResponse {
  id: string;
  human_id: string;
  status: string;
  category: string | null;
  department_name: string | null;
  priority: string | null;
  term: string | null;
  confidence: number | null;
  address: string | null;
  issue_text: string | null;
  image_match_status: ImageMatchStatus | null;
  flags: string[];
  pdf_url: string | null;
}

export interface ConfirmResponse {
  status: string;
  human_id: string;
  duplicate_of_human_id: string | null;
  report_count: number | null;
}

export interface GrievanceSummary {
  id: string;
  human_id: string;
  category: string | null;
  status: string;
  priority: string | null;
  source: GrievanceSource;
  created_at: string;
}

export interface GrievanceEvent {
  status: string;
  note: string | null;
  created_at: string;
}

export interface GrievanceDetail extends GrievanceSummary {
  address: string | null;
  issue_text: string | null;
  department_key: string | null;
  term: string | null;
  confidence: number | null;
  image_match_status: ImageMatchStatus | null;
  flags: string[];
  report_count: number;
  dispatch_ref: string | null;
  events: GrievanceEvent[];
  pdf_url: string | null;
}
