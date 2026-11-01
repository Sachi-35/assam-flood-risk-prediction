import type { District, GeoJsonGeometry } from "../api/types";

export interface DistrictFeature {
  type: "Feature";
  properties: { id: number; name: string };
  geometry: District["geometry"];
}

export interface SkippedDistrict {
  id: number;
  name: string;
  reason: string;
}

export interface GeoResult {
  features: DistrictFeature[];
  /** Districts that could not be drawn. They stay in every list and table; the map shows a warning. */
  skipped: SkippedDistrict[];
}

type Ring = unknown;

function isPosition(p: unknown): p is [number, number] {
  return Array.isArray(p) && p.length >= 2 && typeof p[0] === "number" && typeof p[1] === "number" && Number.isFinite(p[0]) && Number.isFinite(p[1]);
}

/** Returns a reason when a ring is unusable, otherwise null. A ring needs at least 4 positions (closed). */
function ringProblem(ring: Ring): string | null {
  if (!Array.isArray(ring) || ring.length < 4) return "a polygon ring has fewer than 4 points";
  for (const p of ring) {
    if (!isPosition(p)) return "a coordinate is not a pair of numbers";
    if (Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) return "a coordinate is outside longitude/latitude range (expected EPSG:4326)";
  }
  return null;
}

function polygonProblem(poly: unknown): string | null {
  if (!Array.isArray(poly) || poly.length === 0) return "a polygon has no rings";
  for (const ring of poly) {
    const r = ringProblem(ring);
    if (r) return r;
  }
  return null;
}

/** null when the geometry is a drawable Polygon or MultiPolygon; otherwise the reason it is not. */
export function geometryProblem(g: GeoJsonGeometry | null | undefined): string | null {
  if (!g || typeof g !== "object") return "no geometry was returned";
  if (g.type === "Polygon") return polygonProblem(g.coordinates);
  if (g.type === "MultiPolygon") {
    if (!Array.isArray(g.coordinates) || g.coordinates.length === 0) return "a MultiPolygon has no polygons";
    for (const poly of g.coordinates) {
      const r = polygonProblem(poly);
      if (r) return r;
    }
    return null;
  }
  return `geometry type "${String(g.type)}" is not a Polygon or MultiPolygon`;
}

/** Number of separate polygons drawn for a geometry (1 for Polygon, n for MultiPolygon, 0 otherwise). */
export function polygonCount(g: GeoJsonGeometry | null | undefined): number {
  if (!g || geometryProblem(g)) return 0;
  return g.type === "Polygon" ? 1 : (g.coordinates as unknown[]).length;
}

/** Builds map features for every district that has a drawable geometry and reports the rest. Never drops one silently. */
export function buildDistrictFeatures(districts: District[]): GeoResult {
  const features: DistrictFeature[] = [];
  const skipped: SkippedDistrict[] = [];
  for (const d of districts) {
    const problem = geometryProblem(d.geometry);
    if (problem) skipped.push({ id: d.id, name: d.name, reason: problem });
    else features.push({ type: "Feature", properties: { id: d.id, name: d.name }, geometry: d.geometry });
  }
  return { features, skipped };
}

/** Convenience wrapper: only the drawable features. */
export function districtFeatures(districts: District[]): DistrictFeature[] {
  return buildDistrictFeatures(districts).features;
}
