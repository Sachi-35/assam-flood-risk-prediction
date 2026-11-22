import { Link } from "react-router-dom";
import { apiBaseUrl } from "../api/client";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div>
          <h2>Project</h2>
          <p>
            Localized Flood Risk Prediction and Early Warning System Using Machine Learning: an academic capstone project exploring rainfall records,
            historical flood impacts and district vulnerability across the 33 districts of Assam.
          </p>
        </div>
        <div>
          <h2>Explore</h2>
          <Link to="/map">Risk Map</Link>
          <Link to="/history">History</Link>
          <Link to="/recent-rainfall">Recent Rainfall</Link>
          <Link to="/scenario">Hypothetical scenario</Link>
        </div>
        <div>
          <h2>Research</h2>
          <Link to="/ml-experiment">ML Experiment</Link>
          <Link to="/about">About &amp; Method</Link>
          <Link to="/about#limitations">Data limitations</Link>
        </div>
        <p className="footer-disclaimer">
          <strong>Disclaimer.</strong> This is an academic prototype. It is not an official flood-warning service, does not predict floods day by day, and must not be used for
          safety or evacuation decisions. For official information, consult the Assam State Disaster Management Authority and the India Meteorological Department.
          <br />
          <span className="footer-tech">Backend: <code>{apiBaseUrl()}</code></span>
        </p>
      </div>
    </footer>
  );
}
