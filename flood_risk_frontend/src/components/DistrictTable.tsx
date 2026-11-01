import { useMemo } from "react";
import type { Assessment, District } from "../api/types";
import { combinedClass, hazardClass, mm, pct, vulnerabilityClass } from "../lib/assessment";
import { ClassChip } from "./ClassChip";

/** Text alternative to the map: every district, including those with no assessment, each selectable. */
export function DistrictTable({
  districts,
  byDistrict,
  selectedId,
  onSelect,
}: {
  districts: District[];
  byDistrict: Map<number, Assessment>;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const sorted = useMemo(() => [...districts].sort((a, b) => a.name.localeCompare(b.name)), [districts]);
  return (
    <details className="district-table">
      <summary>All {districts.length} districts as a table (text alternative to the map)</summary>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">District</th>
              <th scope="col">Vulnerability</th>
              <th scope="col">Rain hazard</th>
              <th scope="col">Combined</th>
              <th scope="col">Rain in window</th>
              <th scope="col">Days with rain data</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((d) => {
              const a = byDistrict.get(d.id);
              return (
                <tr key={d.id} className={d.id === selectedId ? "selected" : undefined}>
                  <th scope="row">
                    <button type="button" className="link-btn" onClick={() => onSelect(d.id)}>
                      {d.name}
                    </button>
                  </th>
                  <td><ClassChip result={vulnerabilityClass(a)} /></td>
                  <td><ClassChip result={hazardClass(a)} /></td>
                  <td><ClassChip result={combinedClass(a)} /></td>
                  <td>{a ? (mm(a.hazard?.window_rain_mm) ?? "Unknown") : "No assessment"}</td>
                  <td>{a ? (pct(a.hazard?.obs_fraction) ?? "Unknown") : "No assessment"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}
