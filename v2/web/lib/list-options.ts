export const COMPANY_ORDER_OPTIONS = [
  { label: "Recently Updated", value: "updated_desc" },
  { label: "Ticker A-Z", value: "ticker_asc" },
  { label: "Ticker Z-A", value: "ticker_desc" },
  { label: "Name A-Z", value: "name_asc" },
  { label: "Name Z-A", value: "name_desc" },
  { label: "Review Date Soonest", value: "review_date_asc" },
  { label: "Review Date Latest", value: "review_date_desc" },
  { label: "Status", value: "status_asc" },
] as const;

export const REPORT_ORDER_OPTIONS = [
  { label: "Completed Newest", value: "completed_desc" },
  { label: "Completed Oldest", value: "completed_asc" },
  { label: "Updated Newest", value: "updated_desc" },
  { label: "Updated Oldest", value: "updated_asc" },
  { label: "Company A-Z", value: "company_asc" },
  { label: "Company Z-A", value: "company_desc" },
  { label: "Stage", value: "stage_asc" },
  { label: "Result", value: "result_asc" },
  { label: "Title A-Z", value: "title_asc" },
  { label: "Title Z-A", value: "title_desc" },
] as const;

export const COMPANY_BUCKET_OPTIONS = [
  { label: "All Statuses", value: "" },
  { label: "Pool", value: "pool" },
  { label: "Funnel", value: "funnel" },
  { label: "Watchlist", value: "watchlist" },
  { label: "Archive", value: "archive" },
  { label: "Monitoring", value: "monitoring" },
] as const;
