import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link to="/" className="brand" aria-label="Assam Flood Risk: home">
          <span className="brand-mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round">
              <path d="M2 9c3-3 5 3 8 0s5 3 8 0 3 0 4-1M2 16c3-3 5 3 8 0s5 3 8 0 3 0 4-1" />
            </svg>
          </span>
          <span>
            <strong>Assam Flood Risk</strong>
            <small>Academic research prototype</small>
          </span>
        </Link>
        <button type="button" className="menu-toggle" aria-expanded={open} aria-controls="site-nav" onClick={() => setOpen((o) => !o)}>
          {open ? "Close" : "Menu"}
        </button>
        <nav id="site-nav" className={`site-nav${open ? " open" : ""}`} aria-label="Main">
          <NavLink to="/" end>Home</NavLink>
          <div className="nav-group">
            <span className="nav-group-label">Explore</span>
            <NavLink to="/map">Risk Map</NavLink>
            <NavLink to="/history">History</NavLink>
            <NavLink to="/recent-rainfall">Recent Rainfall</NavLink>
            <NavLink to="/scenario">Scenario<span className="nav-tag">hypothetical</span></NavLink>
          </div>
          <div className="nav-group">
            <span className="nav-group-label">Research</span>
            <NavLink to="/ml-experiment">ML Experiment</NavLink>
            <NavLink to="/about">About &amp; Method</NavLink>
          </div>
        </nav>
      </div>
    </header>
  );
}
