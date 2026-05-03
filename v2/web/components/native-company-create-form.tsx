"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, createCompany } from "../lib/api";
import { companyHref } from "../lib/routes";

export function NativeCompanyCreateForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(formData: FormData) {
    const ticker = String(formData.get("ticker") || "").trim().toUpperCase();
    const name = String(formData.get("name") || "").trim();
    const notes = String(formData.get("notes") || "").trim();
    if (!ticker) {
      setError("Ticker is required.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = await createCompany({ ticker, name, notes });
      router.push(companyHref(payload.company));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to create company.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">New Company</p>
          <h2>Create Company</h2>
          <p className="muted">Uses the preserved compatibility API. Ticker remains required; name and notes remain optional.</p>
        </div>
      </div>
      <form action={handleSubmit} className="form-grid create-company-grid">
        <label className="field-block">
          <span className="field-label">Ticker</span>
          <input className="soft-input" name="ticker" placeholder="MSFT" required disabled={busy} />
        </label>
        <label className="field-block">
          <span className="field-label">Name</span>
          <input className="soft-input" name="name" placeholder="Microsoft" disabled={busy} />
        </label>
        <label className="field-block create-company-notes">
          <span className="field-label">Notes</span>
          <textarea
            className="soft-textarea"
            name="notes"
            rows={3}
            placeholder="Optional setup context for the newly created company."
            disabled={busy}
          />
        </label>
        <div className="button-row">
          <button type="submit" className="small-button" disabled={busy}>
            {busy ? "Creating..." : "Create Company"}
          </button>
          {error ? <span className="error-inline">{error}</span> : null}
        </div>
      </form>
    </section>
  );
}
