import L from "leaflet";
import { useEffect } from "react";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import type { Assessment } from "../api/types";
import { COLOR_MODES, type ColorMode } from "../constants";
import { classFor, mm, pct } from "../lib/assessment";
import type { DistrictFeature } from "../lib/geo";
import { patternFill } from "./MapPatterns";

const ASSAM_CENTER: [number, number] = [26.2, 92.9];

function FitToDistricts({ features }: { features: DistrictFeature[] }) {
  const map = useMap();

  useEffect(() => {
    if (!features.length) return;
    const bounds = L.geoJSON(features as never).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [12, 12] });
  }, [features, map]);

  return null;
}

interface Props {
  features: DistrictFeature[];
  assessments: Map<number, Assessment>;
  mode: ColorMode;
  selectedId: number | null;
  dataKey: string;
  onSelect: (id: number) => void;
}

export function ChoroplethMap({
  features,
  assessments,
  mode,
  selectedId,
  dataKey,
  onSelect,
}: Props) {
  const modeLabel = COLOR_MODES.find((m) => m.value === mode)!.label;

  return (
    <MapContainer
      center={ASSAM_CENTER}
      zoom={7}
      className="map"
      scrollWheelZoom
      aria-label="Map of Assam districts coloured by assessment level; grey means unknown"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <FitToDistricts features={features} />

      <GeoJSON
        key={`${dataKey}|${mode}|${selectedId ?? "none"}`}
        data={{ type: "FeatureCollection", features } as never}
        style={(feature) => {
          const properties = feature?.properties as { id: number; name: string };
          const result = classFor(assessments.get(properties.id), mode);
          const selected = properties.id === selectedId;

          return {
            fillColor: patternFill(result.cls),
            fillOpacity: 0.92,
            color: selected ? "#0b1220" : "#475569",
            weight: selected ? 3.5 : 1,
          };
        }}
        onEachFeature={(feature, layer) => {
          const { id, name } = feature.properties as {
            id: number;
            name: string;
          };

          const assessment = assessments.get(id);
          const result = classFor(assessment, mode);

          const tip = document.createElement("div");
          const strong = document.createElement("strong");
          strong.textContent = name;
          tip.append(strong, document.createElement("br"));
          tip.append(`${modeLabel}: ${result.label}`);

          if (mode !== "vulnerability") {
            tip.append(
              document.createElement("br"),
              `Rain in window: ${mm(assessment?.hazard?.window_rain_mm) ?? "Unknown"}`,
              document.createElement("br"),
              `Observation coverage: ${pct(assessment?.hazard?.obs_fraction) ?? "Unknown"}`,
            );
          }

          if (result.reason) {
            tip.append(document.createElement("br"), result.reason);
          }

          layer.bindTooltip(tip, { sticky: true });

          const path = layer as L.Path;
          layer.on({
            click: () => onSelect(id),
            mouseover: () => path.setStyle({ weight: 2.5, color: "#0b1220" }),
            mouseout: () =>
              path.setStyle({
                weight: id === selectedId ? 3.5 : 1,
                color: id === selectedId ? "#0b1220" : "#475569",
              }),
            add: () => {
              const element = path.getElement() as SVGElement | undefined;
              if (!element) return;

              element.setAttribute("tabindex", "0");
              element.setAttribute("role", "button");
              element.setAttribute(
                "aria-label",
                `${name}: ${modeLabel} ${result.label}. Press Enter to open details.`,
              );

              element.addEventListener("keydown", (event) => {
                const key = (event as KeyboardEvent).key;
                if (key === "Enter" || key === " ") {
                  event.preventDefault();
                  onSelect(id);
                }
              });
            },
          });
        }}
      />
    </MapContainer>
  );
}
