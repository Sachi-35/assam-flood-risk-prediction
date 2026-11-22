import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { MapPatterns } from "./components/MapPatterns";
import { SiteFooter } from "./components/SiteFooter";
import { SiteHeader } from "./components/SiteHeader";
import { AboutPage } from "./pages/AboutPage";
import { HistoryPage } from "./pages/HistoryPage";
import { HomePage } from "./pages/HomePage";
import { MapPage } from "./pages/MapPage";
import { ScenarioPage } from "./pages/ScenarioPage";
import { RecentRainfallPage } from "./pages/RecentRainfallPage";
// import { RainfallArchivePage } from "./pages/RainfallArchivePage";
import { MLExperimentPage } from "./pages/MLExperimentPage";

/** The map used to live at "/". Old links that carry map parameters are sent to /map with the parameters kept. */
function Home() {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (["district", "mode", "window", "date"].some((k) => params.has(k))) return <Navigate to={`/map${search}`} replace />;
  return <HomePage />;
}

export default function App() {
  return (
    <>
      <MapPatterns />
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <SiteHeader />
      <main id="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/recent-rainfall" element={<RecentRainfallPage />} />
          {/* <Route path="/rainfall-archive" element={<RainfallArchivePage />} /> */}
          <Route path="/ml-experiment" element={<MLExperimentPage />} />
          <Route path="/scenario" element={<ScenarioPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="*" element={<div className="page"><h1>Page not found</h1><NavLink to="/map">Back to the map</NavLink></div>} />
        </Routes>
      </main>
      <SiteFooter />
    </>
  );
}
