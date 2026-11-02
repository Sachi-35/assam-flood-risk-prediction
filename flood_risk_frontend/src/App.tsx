import { NavLink, Route, Routes } from "react-router-dom";
import { apiBaseUrl } from "./api/client";
import { MapPatterns } from "./components/MapPatterns";
import { AboutPage } from "./pages/AboutPage";
import { HistoryPage } from "./pages/HistoryPage";
import { MapPage } from "./pages/MapPage";
import { ScenarioPage } from "./pages/ScenarioPage";
import { RecentRainfallPage } from "./pages/RecentRainfallPage";

export default function App() {
  return (
    <>
      <MapPatterns />
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">≈</span>
          <div>
            <strong>Assam Flood Risk</strong>
            <small>Seasonal district-level assessment · academic prototype</small>
          </div>
        </div>
        <nav aria-label="Main">
          <NavLink to="/" end>Map</NavLink>
          <NavLink to="/history">History</NavLink>
          <NavLink to="/recent-rainfall">Recent rainfall</NavLink>
          <NavLink to="/scenario">Rainfall scenario</NavLink>
          <NavLink to="/about">About &amp; method</NavLink>
        </nav>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<MapPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/recent-rainfall" element={<RecentRainfallPage />} />
          <Route path="/scenario" element={<ScenarioPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="*" element={<div className="page"><h1>Page not found</h1><NavLink to="/">Back to the map</NavLink></div>} />
        </Routes>
      </main>
      <footer className="app-footer">
        Academic capstone prototype. Not an official flood-warning service and not a day-by-day prediction. Backend: <code>{apiBaseUrl()}</code>
      </footer>
    </>
  );
}
