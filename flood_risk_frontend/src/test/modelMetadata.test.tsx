import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { ModelMetadata } from "../api/types";
import { ModelMetadataPanel, ModelMetadataView } from "../components/ModelMetadataPanel";

afterEach(() => vi.restoreAllMocks());

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));
}

describe("GET /model/metadata handling", () => {
  it("turns a 503 into an 'untrained' result instead of throwing", async () => {
    mockFetch(503, { detail: "No trained model found. Run `python scripts/train_model.py`." });
    const r = await api.modelMetadata();
    expect(r).toEqual({ kind: "untrained", detail: expect.stringContaining("train_model.py") });
  });

  it("still throws for other HTTP errors and for an unreachable backend", async () => {
    mockFetch(500, { detail: "boom" });
    await expect(api.modelMetadata()).rejects.toMatchObject({ kind: "http", status: 500 });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(api.modelMetadata()).rejects.toMatchObject({ kind: "network" });
  });
});

describe("ModelMetadataPanel", () => {
  it("shows the untrained state with the commands to run", async () => {
    vi.spyOn(api, "modelMetadata").mockResolvedValue({ kind: "untrained", detail: "No trained model found." });
    render(<ModelMetadataPanel />);
    expect(await screen.findByText(/has not been trained yet/i)).toBeInTheDocument();
    expect(screen.getByText("python scripts/train_model.py")).toBeInTheDocument();
    expect(screen.getByText("python scripts/seed_db.py --reset")).toBeInTheDocument();
    expect(screen.getByText(/python scripts\/compute_assessments\.py/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // not treated as an error
  });

  it("shows the backend-not-running state for a network failure", async () => {
    vi.spyOn(api, "modelMetadata").mockRejectedValue(new ApiError("network", null, "Failed to fetch"));
    render(<ModelMetadataPanel />);
    expect(await screen.findByText(/can't reach the backend/i)).toBeInTheDocument();
  });
});

const meta: ModelMetadata = {
  model_version: "rf_test", model_type: "RandomForestClassifier", trained_at: "2026-01-02T03:04:05+00:00", training_rows: 160,
  feature_list: ["season_total_mm"], class_counts: { low: 40, moderate: 40, high: 40, severe: 40 },
  vulnerability_source: "district_history",
  cross_validation: {
    scheme: "leave_one_year_out", n_out_of_fold: 160, caveat: "Small sample.",
    model: { macro_f1: 0.3, qwk: 0.2, within_1_class: 0.7, ordinal_mae: 1 },
    majority: { macro_f1: 0.1, qwk: 0, within_1_class: 0.6, ordinal_mae: 1.2 },
    district_mean_other_years: { macro_f1: 0.4, qwk: 0.5, within_1_class: 0.8, ordinal_mae: 0.8 },
  },
  thresholds: null, notes: "Test notes.",
};

describe("ModelMetadataView", () => {
  it("says so when the model did not beat the baselines, and marks the best kappa", () => {
    render(<ModelMetadataView meta={meta} />);
    const notice = document.querySelector(".notice.warn")!;
    expect(notice.textContent).toMatch(/did not beat the baselines/);
    expect(notice.textContent).toMatch(/Empirical history/);
    expect(screen.getByText(/district's own mean class in the other years ★/)).toBeInTheDocument();
    expect(screen.getByText("Small sample.")).toBeInTheDocument();
  });
});
