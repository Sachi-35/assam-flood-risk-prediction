import { useMemo } from "react";
import type { Assessment, District } from "../api/types";
import { DEMO_RAINFALL, displayedClass } from "../lib/demoRainfall";
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

      <p className="demo-data-note">
        Illustrative rainfall demo values · not observed measurements
      </p>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">District</th>
              <th scope="col">Vulnerability</th>
              <th scope="col">Rain hazard</th>
              <th scope="col">Combined</th>
              <th scope="col">Rain in demo window</th>
              <th scope="col">Days represented</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((d) => {
              const a = byDistrict.get(d.id);
              const demo = DEMO_RAINFALL[d.name];
              const vulnerability = displayedClass(a, "vulnerability", d.name);
              const hazard = displayedClass(a, "hazard", d.name);
              const combined = displayedClass(a, "combined", d.name);

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
                  <td>{!a ? "No assessment" : demo ? `${demo.rain.toFixed(1)} mm` : "No demo value"}</td>
                  <td>{!a ? "No assessment" : demo ? `${demo.days} days` : "No demo value"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}
