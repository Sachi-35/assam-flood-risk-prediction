import { useMemo } from "react";
import type { Assessment, District } from "../api/types";
import { classFor, mm, pct } from "../lib/assessment";
import { ClassChip } from "./ClassChip";

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
  const sorted = useMemo(
    () => [...districts].sort((a, b) => a.name.localeCompare(b.name)),
    [districts],
  );

  return (
    <details className="district-table">
      <summary>
        All {districts.length} districts as a table (text alternative to the map)
      </summary>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">District</th>
              <th scope="col">Vulnerability</th>
              <th scope="col">Rain hazard</th>
              <th scope="col">Combined</th>
              <th scope="col">Rain in window</th>
              <th scope="col">Observation coverage</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((d) => {
              const a = byDistrict.get(d.id);
              const vulnerability = classFor(a, "vulnerability");
              const hazard = classFor(a, "hazard");
              const combined = classFor(a, "combined");

              return (
                <tr
                  key={d.id}
                  className={d.id === selectedId ? "selected" : undefined}
                >
                  <th scope="row">
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => onSelect(d.id)}
                    >
                      {d.name}
                    </button>
                  </th>
                  <td><ClassChip result={vulnerability} /></td>
                  <td><ClassChip result={hazard} /></td>
                  <td><ClassChip result={combined} /></td>
                  <td>{a ? mm(a.hazard?.window_rain_mm) ?? "Unknown" : "No assessment"}</td>
                  <td>{a ? pct(a.hazard?.obs_fraction) ?? "Unknown" : "No assessment"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}
