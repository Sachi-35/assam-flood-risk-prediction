import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import { DistrictPanel } from "../components/DistrictPanel";
import { DistrictTable } from "../components/DistrictTable";
import { ImpactTimelineView } from "../components/FloodImpactSection";
import { SummaryStrip } from "../components/SummaryStrip";
import { summarize } from "../lib/summary";
import { make33Districts, makeAssessment, makeDistrict } from "./fixtures";

/** Everything here uses SYNTHETIC districts and records and a mocked API. It is not a test against the real backend. */
afterEach(() => vi.restoreAllMocks());

const wrap = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("a district with no assessment stays usable (mocked API)", () => {
  it("still shows its name, terrain and history, and says the assessment is unavailable", async () => {
    vi.spyOn(api, "districtAssessment").mockRejectedValue(new ApiError("http", 404, "Not found"));
    vi.spyOn(api, "floodImpact").mockResolvedValue({ kind: "unavailable", detail: "Not Found" });
    wrap(<DistrictPanel district={makeDistrict(7)} windowDays={7} date="2023-07-10" onClose={() => {}} />);

    expect(screen.getByRole("heading", { name: "Synthetic 7" })).toBeInTheDocument();
    expect(await screen.findByText("No assessment available")).toBeInTheDocument();
    expect(screen.getAllByText(/does not mean Low risk/i).length).toBeGreaterThan(0);
    // Terrain values are null in the district, so they read "Not available", never 0.
    expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(5);
    expect(screen.queryByText(/^0 m$/)).not.toBeInTheDocument();
    expect(screen.getByText(/digital surface model/i)).toBeInTheDocument();
    expect(screen.getByText(/have not been verified/i)).toBeInTheDocument();
    // History: backend gap is explained and all five years are unknown, not zero.
    expect(await screen.findByText(/not available from the backend/i)).toBeInTheDocument();
    expect(document.querySelectorAll('[data-kind="unknown"]')).toHaveLength(5);
  });

  it("shows the assessment, separate parts and flood-impact records when they exist", async () => {
    vi.spyOn(api, "districtAssessment").mockResolvedValue(makeAssessment());
    vi.spyOn(api, "floodImpact").mockResolvedValue({
      kind: "ok",
      records: [
        { year: 2022, status: "reported", impact_class: "moderate", affected_population: 4000 },
        { year: 2023, status: "no_reported_impact" },
      ],
    });
    wrap(<DistrictPanel district={makeDistrict(3, undefined, { mean_elevation_m: 55 })} windowDays={7} date={null} onClose={() => {}} />);
    expect(await screen.findByRole("heading", { name: "District vulnerability" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rain hazard" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Combined risk category" })).toBeInTheDocument();
    expect(screen.getByText("55 m")).toBeInTheDocument();
    await screen.findByText("No reported impact");
    expect(document.querySelectorAll('[data-kind="reported"]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-kind="none_reported"]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-kind="unknown"]')).toHaveLength(3);
  });

  it("does not request an assessment when the backend offers no rainfall window", async () => {
    const spy = vi.spyOn(api, "districtAssessment");
    vi.spyOn(api, "floodImpact").mockResolvedValue({ kind: "ok", records: [] });
    wrap(<DistrictPanel district={makeDistrict(1)} windowDays={null} date={null} onClose={() => {}} />);
    expect(await screen.findByText("No assessment available")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("flood-impact timeline", () => {
  it("shows missing counts as 'not available' and never as 0", () => {
    render(<ImpactTimelineView records={[{ year: 2021, status: "reported", impact_class: "high" }]} />);
    expect(screen.getByText(/Affected: not available/)).toBeInTheDocument();
    expect(screen.queryByText(/Affected: 0\b/)).not.toBeInTheDocument();
    expect(screen.getByText(/4 unknown/)).toBeInTheDocument();
  });

  it("shows the documented caveats for 2019 and 2020", () => {
    render(<ImpactTimelineView records={[]} />);
    expect(screen.getByText(/fourth-wave snapshot/i)).toBeInTheDocument();
    expect(screen.getByText(/does not reconcile/i)).toBeInTheDocument();
  });
});

describe("district table lists every district", () => {
  it("includes all 33 districts, with and without assessments, and each is selectable", async () => {
    const districts = make33Districts();
    const onSelect = vi.fn();
    const byDistrict = new Map([[1, makeAssessment({ district_id: 1 })]]);
    render(<DistrictTable districts={districts} byDistrict={byDistrict} selectedId={null} onSelect={onSelect} />);
    expect(screen.getAllByRole("row")).toHaveLength(34); // header + 33
    const row = screen.getByRole("button", { name: "Synthetic 20" }).closest("tr")!;
    expect(within(row).getAllByText(/Unknown/, { selector: ".chip" })).toHaveLength(3);
    expect(within(row).getAllByText("No assessment")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Synthetic 20" }));
    expect(onSelect).toHaveBeenCalledWith(20);
  });
});

describe("overview strip", () => {
  it("reports unknown districts and warns when the district count is not the 33 expected", () => {
    const eight = make33Districts().slice(0, 8);
    wrap(<SummaryStrip summary={summarize(eight, new Map(), "vulnerability")} mode="vulnerability" periodLabel="No stored assessments" undrawn={2} />);
    expect(screen.getByText("Unknown or unavailable").nextSibling).toHaveTextContent("8");
    expect(screen.getByText(/backend returned 8/)).toBeInTheDocument();
    expect(screen.getByText(/2 district\(s\) have unusable geometry/)).toBeInTheDocument();
    expect(screen.getByText(/Everything on this page is stored data/)).toBeInTheDocument();
  });
});
