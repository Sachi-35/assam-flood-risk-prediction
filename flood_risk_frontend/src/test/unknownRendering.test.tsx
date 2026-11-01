import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AssessmentView } from "../components/DistrictPanel";
import { ClassChip } from "../components/ClassChip";
import { combinedClass } from "../lib/assessment";
import { historyVulnerability, insufficientRain, makeAssessment } from "./fixtures";

const renderView = (a = insufficientRain) =>
  render(
    <MemoryRouter>
      <AssessmentView assessment={a} />
    </MemoryRouter>,
  );

describe("Unknown status rendering", () => {
  it("shows 'Unknown' with the reason, and never 'Low', when rainfall data is insufficient", () => {
    renderView();
    const hazard = screen.getByRole("heading", { name: "Rain hazard" }).closest("section")!;
    expect(within(hazard).getByText(/Unknown/, { selector: ".chip" })).toBeInTheDocument();
    expect(within(hazard).queryByText(/^\W*\s*Low$/)).not.toBeInTheDocument();
    expect(within(hazard).getAllByText(/Too few days/i).length).toBeGreaterThan(0);

    const combined = screen.getByRole("heading", { name: "Combined risk category" }).closest("section")!;
    expect(within(combined).getByText(/Unknown/, { selector: ".chip" })).toBeInTheDocument();
  });

  it("shows rain and observed share as Unknown rather than 0", () => {
    renderView();
    expect(screen.getByText(/Rain in window:/).textContent).toMatch(/Unknown/);
    expect(screen.getByText(/Days with rainfall data:/).textContent).toMatch(/40%/);
    expect(screen.queryByText(/0\.0 mm/)).not.toBeInTheDocument();
  });

  it("explains the missing values in a status note", () => {
    renderView();
    expect(screen.getByText(/Some values are Unknown/)).toBeInTheDocument();
  });

  it("renders a grey chip carrying the reason as its title", () => {
    render(<ClassChip result={combinedClass(insufficientRain)} />);
    const chip = screen.getByText(/Unknown/);
    expect(chip).toHaveAttribute("data-class", "unknown");
    expect(chip).toHaveAttribute("title");
    expect(chip.getAttribute("style")).toMatch(/background: rgb\(201, 206, 214\)/);
  });

  it("states that empirical-history vulnerability has no probabilities or SHAP", () => {
    renderView(historyVulnerability);
    expect(screen.getByText(/no class probabilities and no SHAP explanation/i)).toBeInTheDocument();
    expect(screen.getByText("Empirical history", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.queryByText("Class probabilities")).not.toBeInTheDocument();
  });

  it("labels the three components with their type badges", () => {
    renderView(makeAssessment());
    expect(screen.getAllByText("Rule-based", { selector: ".badge" })).toHaveLength(2);
    expect(screen.getByText("ML estimate", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.getByText("Class probabilities")).toBeInTheDocument();
    expect(screen.getByText("Top features behind the estimate")).toBeInTheDocument();
  });
});
