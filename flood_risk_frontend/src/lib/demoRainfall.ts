import type { Assessment, RiskClass } from "../api/types";
import type { ColorMode } from "../constants";
import {
  classFor,
  knownResult,
  unknownResult,
  vulnerabilityClass,
  type ClassResult,
} from "./assessment";

export const DEMO_RAINFALL: Record<
  string,
  { hazard: RiskClass; rain: number; days: number }
> = {
  Baksa: { hazard: "high", rain: 186.4, days: 7 },
  Barpeta: { hazard: "severe", rain: 243.8, days: 7 },
  Biswanath: { hazard: "moderate", rain: 112.6, days: 6 },
  Bongaigaon: { hazard: "high", rain: 178.2, days: 7 },
  Cachar: { hazard: "moderate", rain: 96.5, days: 5 },
  Charaideo: { hazard: "moderate", rain: 121.7, days: 6 },
  Chirang: { hazard: "high", rain: 194.3, days: 7 },
  Darrang: { hazard: "high", rain: 167.9, days: 6 },
  Dhemaji: { hazard: "severe", rain: 267.5, days: 7 },
  Dhubri: { hazard: "high", rain: 205.6, days: 7 },
  Dibrugarh: { hazard: "moderate", rain: 104.2, days: 6 },
  "Dima Hasao": { hazard: "moderate", rain: 88.4, days: 5 },
  Goalpara: { hazard: "severe", rain: 231.6, days: 7 },
  Golaghat: { hazard: "moderate", rain: 118.3, days: 6 },
  Hailakandi: { hazard: "high", rain: 172.8, days: 6 },
  Hojai: { hazard: "moderate", rain: 109.5, days: 5 },
  Jorhat: { hazard: "low", rain: 48.6, days: 5 },
  Kamrup: { hazard: "moderate", rain: 132.4, days: 6 },
  "Kamrup Metropolitan": { hazard: "moderate", rain: 91.8, days: 5 },
  "Karbi Anglong": { hazard: "low", rain: 42.7, days: 4 },
  Karimganj: { hazard: "high", rain: 188.9, days: 7 },
  Kokrajhar: { hazard: "moderate", rain: 126.3, days: 6 },
  Lakhimpur: { hazard: "severe", rain: 254.1, days: 7 },
  Majuli: { hazard: "high", rain: 198.7, days: 7 },
  Morigaon: { hazard: "high", rain: 183.5, days: 6 },
  Nagaon: { hazard: "moderate", rain: 115.2, days: 6 },
  Nalbari: { hazard: "high", rain: 176.8, days: 7 },
  Sivasagar: { hazard: "low", rain: 55.3, days: 5 },
  Sonitpur: { hazard: "moderate", rain: 123.9, days: 6 },
  "South Salmara Mankachar": { hazard: "high", rain: 201.4, days: 7 },
  Tinsukia: { hazard: "low", rain: 61.2, days: 5 },
  Udalguri: { hazard: "moderate", rain: 107.6, days: 6 },
  "West Karbi Anglong": { hazard: "high", rain: 169.3, days: 6 },
};

const CLASS_RANK: Record<RiskClass, number> = {
  low: 0,
  moderate: 1,
  high: 2,
  severe: 3,
};

export function demoHazardClass(name: string): ClassResult {
  const demo = DEMO_RAINFALL[name];
  return demo ? knownResult(demo.hazard) : unknownResult("No illustrative demo value is available.");
}

export function demoCombinedClass(
  assessment: Assessment | undefined,
  name: string,
): ClassResult {
  const vulnerability = vulnerabilityClass(assessment);
  const demo = DEMO_RAINFALL[name];

  if (!demo) return unknownResult("No illustrative demo value is available.");
  if (vulnerability.cls === "unknown") {
    return unknownResult("Vulnerability is unavailable for this district.");
  }

  const vulnerabilityRisk = vulnerability.cls as RiskClass;
  return knownResult(
    CLASS_RANK[vulnerabilityRisk] >= CLASS_RANK[demo.hazard]
      ? vulnerabilityRisk
      : demo.hazard,
  );
}

export function displayedClass(
  assessment: Assessment | undefined,
  mode: ColorMode,
  districtName: string,
): ClassResult {
  if (mode === "vulnerability") return classFor(assessment, mode);
  if (!DEMO_RAINFALL[districtName]) return classFor(assessment, mode);
  if (mode === "hazard") return demoHazardClass(districtName);
  return demoCombinedClass(assessment, districtName);
}
