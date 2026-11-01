import L from "leaflet";
import { useEffect } from "react";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import type { Assessment } from "../api/types";
import { COLOR_MODES, type ColorMode } from "../constants";
import { classFor } from "../lib/assessment";
import type { DistrictFeature } from "../lib/geo";
import { patternFill } from "./MapPatterns";

const ASSAM_CENTER: [number, number] = [26.2, 92.9];

function FitToDistricts({ features }: { features: DistrictFeature[] }) {
  const map = useMap();
  useEffect(() => {
    if (!features.length) return;
    const b = L.geoJSON(features as never).getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [12, 12] });
  }, [features, map]);
  return null;
}

interface Props {
  /** Drawable features (see buildDistrictFeatures). Districts without an assessment are included and stay clickable. */
  features: DistrictFeature[];
  assessments: Map<number, Assessment>;
  mode: ColorMode;
  selectedId: number | null;
  /** Changes whenever the assessments change (window/date), forcing the layer to restyle. */
  dataKey: string;
  onSelect: (id: number) => void;
}

export function ChoroplethMap({ features, assessments, mode, selectedId, dataKey, onSelect }: Props) {
  const modeLabel = COLOR_MODES.find((m) => m.value === mode)!.label;

  return (
    <MapContainer center={ASSAM_CENTER} zoom={7} className="map" scrollWheelZoom aria-label="Map of Assam districts coloured by assessment level; grey means unknown">
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitToDistricts features={features} />
      <GeoJSON
        key={`${dataKey}|${mode}|${selectedId ?? "none"}`}
        data={{ type: "FeatureCollection", features } as never}
        style={(f) => {
          const id = (f?.properties as { id: number }).id;
          const res = classFor(assessments.get(id), mode);
          const selected = id === selectedId;
          return {
            fillColor: patternFill(res.cls),
            fillOpacity: 0.92,
            color: selected ? "#0b1220" : "#475569",
            weight: selected ? 3.5 : 1,
          };
        }}
        onEachFeature={(f, layer) => {
          const { id, name } = f.properties as { id: number; name: string };
          const res = classFor(assessments.get(id), mode);

          const tip = document.createElement("div");
          const strong = document.createElement("strong");
          strong.textContent = name;
          tip.append(strong, document.createElement("br"), `${modeLabel}: ${res.label}`);
          if (!assessments.has(id)) tip.append(document.createElement("br"), "No assessment stored");
          layer.bindTooltip(tip, { sticky: true });

          const path = layer as L.Path;
          layer.on({
            click: () => onSelect(id),
            mouseover: () => path.setStyle({ weight: 2.5, color: "#0b1220" }),
            mouseout: () => path.setStyle({ weight: id === selectedId ? 3.5 : 1, color: id === selectedId ? "#0b1220" : "#475569" }),
            add: () => {
              // Make each district reachable and operable from the keyboard.
              const el = path.getElement() as SVGElement | undefined;
              if (!el) return;
              el.setAttribute("tabindex", "0");
              el.setAttribute("role", "button");
              el.setAttribute("aria-label", `${name}: ${modeLabel} ${res.label}${assessments.has(id) ? "" : " (no assessment stored)"}. Press Enter to open details.`);
              el.addEventListener("keydown", (e) => {
                const k = (e as KeyboardEvent).key;
                if (k === "Enter" || k === " ") {
                  e.preventDefault();
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
