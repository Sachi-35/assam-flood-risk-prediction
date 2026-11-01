import { describe, expect, it } from "vitest";
import { CLASS_ORDER, CLASS_STYLE, COMPONENT_BADGE, HAZARD_LEVEL_CLASS } from "../constants";
import { classFor, combinedClass, hazardClass, vulnerabilityClass } from "../lib/assessment";
import { historyVulnerability, insufficientRain, makeAssessment } from "./fixtures";

describe("class colour mapping", () => {
  it("gives each of the four classes and Unknown a distinct colour", () => {
    const colors = [...CLASS_ORDER, "unknown" as const].map((c) => CLASS_STYLE[c].color);
    expect(new Set(colors).size).toBe(5);
  });

  it("uses distinct patterns, so classes do not depend on colour alone", () => {
    const patterns = [...CLASS_ORDER, "unknown" as const].map((c) => CLASS_STYLE[c].pattern);
    expect(new Set(patterns).size).toBe(5);
  });

  it("makes Unknown a neutral grey (r≈g≈b)", () => {
    const hex = CLASS_STYLE.unknown.color.slice(1);
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
    expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(20);
  });

  it("darkens monotonically from Low to Severe", () => {
    const lum = (hex: string) => {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const l = CLASS_ORDER.map((c) => lum(CLASS_STYLE[c].color));
    expect(l).toEqual([...l].sort((a, b) => b - a));
  });

  it("maps hazard levels 0..3 to low..severe", () => {
    expect(HAZARD_LEVEL_CLASS).toEqual(["low", "moderate", "high", "severe"]);
    for (let lvl = 0; lvl <= 3; lvl++) {
      const a = makeAssessment({ hazard: { ...makeAssessment().hazard, level: lvl } });
      expect(hazardClass(a).cls).toBe(CLASS_ORDER[lvl]);
    }
  });

  it("has badge text for every backend component_type", () => {
    expect(COMPONENT_BADGE.rule_based.text).toBe("Rule-based");
    expect(COMPONENT_BADGE.rule_based_combination.text).toBe("Rule-based");
    expect(COMPONENT_BADGE.ml_estimate.text).toBe("ML estimate");
    expect(COMPONENT_BADGE.empirical_history.text).toBe("Empirical history");
  });
});

describe("unknown handling", () => {
  it("never maps missing data to Low", () => {
    expect(hazardClass(insufficientRain).cls).toBe("unknown");
    expect(combinedClass(insufficientRain).cls).toBe("unknown");
    expect(combinedClass(undefined).cls).toBe("unknown");
    expect(hazardClass(null).cls).toBe("unknown");
  });

  it("treats hazard level 0 as a real Low, not as missing", () => {
    const a = makeAssessment({ hazard: { ...makeAssessment().hazard, level: 0 } });
    expect(hazardClass(a).cls).toBe("low");
  });

  it("carries the reason from the backend status", () => {
    expect(hazardClass(insufficientRain).reason).toMatch(/rainfall data/i);
    const noClim = makeAssessment({ status: "no_climatology", hazard: { ...makeAssessment().hazard, level: null } });
    expect(hazardClass(noClim).reason).toMatch(/baseline/i);
  });

  it("still colours by vulnerability when rainfall is missing", () => {
    expect(vulnerabilityClass(insufficientRain).cls).toBe("high");
    expect(classFor(insufficientRain, "vulnerability").cls).toBe("high");
    expect(classFor(insufficientRain, "combined").cls).toBe("unknown");
  });

  it("is Unknown when no vulnerability exists", () => {
    const a = makeAssessment({ status: "vulnerability_unavailable", vulnerability: null, combined: { component_type: "rule_based_combination", risk_class: null, risk_score: null } });
    expect(vulnerabilityClass(a).cls).toBe("unknown");
    expect(hazardClass(a).cls).toBe("moderate"); // hazard itself is still known
  });

  it("rejects class names it does not recognise", () => {
    const a = makeAssessment({ combined: { component_type: "rule_based_combination", risk_class: "banana", risk_score: 0.1 } });
    expect(combinedClass(a).cls).toBe("unknown");
  });

  it("keeps the history fixture valid", () => {
    expect(vulnerabilityClass(historyVulnerability).cls).toBe("moderate");
  });
});
