import { describe, expect, it } from "vitest";
import { buildDistrictFeatures, geometryProblem, polygonCount } from "../lib/geo";
import { make33Districts, makeDistrict, multiPolygon, polygon } from "./fixtures";

/** SYNTHETIC geometries only. These tests check the code paths, not the real Assam boundary file. */
describe("geometry handling (synthetic data)", () => {
  it("accepts Polygon and MultiPolygon", () => {
    expect(geometryProblem(polygon(90, 25))).toBeNull();
    expect(geometryProblem(multiPolygon(90, 25))).toBeNull();
    expect(polygonCount(polygon(90, 25))).toBe(1);
    expect(polygonCount(multiPolygon(90, 25))).toBe(2);
  });

  it("keeps all 33 districts, with no hardcoded list, mixing Polygon and MultiPolygon", () => {
    const districts = make33Districts();
    const { features, skipped } = buildDistrictFeatures(districts);
    expect(districts.filter((d) => d.geometry.type === "MultiPolygon").length).toBeGreaterThan(0);
    expect(districts.filter((d) => d.geometry.type === "Polygon").length).toBeGreaterThan(0);
    expect(features).toHaveLength(33);
    expect(skipped).toEqual([]);
    expect(new Set(features.map((f) => f.properties.id)).size).toBe(33);
  });

  it("handles a different number of districts (not tied to 8 or 33)", () => {
    expect(buildDistrictFeatures(make33Districts().slice(0, 8)).features).toHaveLength(8);
    expect(buildDistrictFeatures([]).features).toHaveLength(0);
  });

  it("reports, rather than silently drops, districts it cannot draw", () => {
    const bad = [
      makeDistrict(1, { type: "Point", coordinates: [90, 25] }),
      makeDistrict(2, { type: "Polygon", coordinates: [] }),
      makeDistrict(3, { type: "Polygon", coordinates: [[[90, 25], [91, 25]]] }),
      makeDistrict(4, { type: "Polygon", coordinates: [[[1e6, 25], [1e6, 26], [1e6 + 1, 26], [1e6, 25]]] }),
      makeDistrict(5, null as never),
      makeDistrict(6),
    ];
    const { features, skipped } = buildDistrictFeatures(bad);
    expect(features.map((f) => f.properties.id)).toEqual([6]);
    expect(skipped.map((s) => s.id)).toEqual([1, 2, 3, 4, 5]);
    expect(skipped.every((s) => s.reason.length > 0)).toBe(true);
    expect(skipped.find((s) => s.id === 4)!.reason).toMatch(/EPSG:4326/);
    expect(features.length + skipped.length).toBe(bad.length);
  });
});
