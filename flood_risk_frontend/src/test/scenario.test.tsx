import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { District } from "../api/types";
import { validateScenario, type ScenarioFormValues } from "../lib/scenario";
import { ScenarioForm } from "../pages/ScenarioPage";

const WINDOWS = [3, 7, 15, 30];
const good: ScenarioFormValues = { districtId: "4", windowDays: "7", endDate: "2023-07-10", rainMm: "120" };

describe("validateScenario", () => {
  it("accepts a complete, in-range form and builds the request body", () => {
    const r = validateScenario(good, WINDOWS);
    expect(r.errors).toEqual({});
    expect(r.request).toEqual({ district_id: 4, window_days: 7, window_end_date: "2023-07-10", window_rain_mm: 120 });
  });

  it("accepts the bounds 0 and 2000 mm", () => {
    expect(validateScenario({ ...good, rainMm: "0" }, WINDOWS).request?.window_rain_mm).toBe(0);
    expect(validateScenario({ ...good, rainMm: "2000" }, WINDOWS).request?.window_rain_mm).toBe(2000);
  });

  it.each([
    ["", "Enter the total rain"],
    ["abc", "number"],
    ["-1", "negative"],
    ["2000.5", "at most 2000"],
  ])("rejects rain %j", (rainMm, msg) => {
    const r = validateScenario({ ...good, rainMm }, WINDOWS);
    expect(r.request).toBeUndefined();
    expect(r.errors.rainMm).toContain(msg);
  });

  it("requires district, a supported window and a real date", () => {
    const r = validateScenario({ districtId: "", windowDays: "5", endDate: "2023-02-30", rainMm: "10" }, WINDOWS);
    expect(r.errors.districtId).toBeDefined();
    expect(r.errors.windowDays).toMatch(/3, 7, 15, 30/);
    expect(r.errors.endDate).toMatch(/valid date/);
    expect(validateScenario({ ...good, endDate: "" }, WINDOWS).errors.endDate).toMatch(/Enter the date/);
  });
});

const districts = [{ id: 4, name: "Dhemaji" }, { id: 5, name: "Jorhat" }] as District[];

describe("ScenarioForm", () => {
  it("shows errors and does not submit when the form is empty", async () => {
    const onSubmit = vi.fn();
    render(<ScenarioForm districts={districts} windows={WINDOWS} initial={{ districtId: "", windowDays: "", endDate: "", rainMm: "" }} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /run hypothetical scenario/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("Choose a district.")).toBeInTheDocument();
  });

  it("rejects an out-of-range rain total", async () => {
    const onSubmit = vi.fn();
    render(<ScenarioForm districts={districts} windows={WINDOWS} initial={good} onSubmit={onSubmit} />);
    const rain = screen.getByLabelText(/total rain/i);
    await userEvent.clear(rain);
    await userEvent.type(rain, "2500");
    await userEvent.click(screen.getByRole("button", { name: /run hypothetical scenario/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/at most 2000 mm/)).toBeInTheDocument();
  });

  it("submits the typed request when valid", async () => {
    const onSubmit = vi.fn();
    render(<ScenarioForm districts={districts} windows={WINDOWS} initial={good} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /run hypothetical scenario/i }));
    expect(onSubmit).toHaveBeenCalledWith({ district_id: 4, window_days: 7, window_end_date: "2023-07-10", window_rain_mm: 120 });
  });
});
