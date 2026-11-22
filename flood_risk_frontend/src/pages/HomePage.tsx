import { Link } from "react-router-dom";
import { DATA_FACTS } from "../constants";

const FEATURES = [
  {
    to: "/map",
    title: "District Risk Map",
    what: "A choropleth map of all 33 districts, coloured by seasonal vulnerability, rain hazard or a rule-based combination.",
    learn: "Which districts have historically been most affected, and where information is simply unavailable.",
  },
  {
    to: "/history",
    title: "Flood History",
    what: "Year-by-year historical flood-impact records for a district, alongside its stored rainfall record.",
    learn: "How a district's reported impact has varied between seasons, and which years have no usable record.",
  },
  {
    to: "/recent-rainfall",
    title: "Recent Rainfall",
    what: "Daily district-level rainfall observations from 2019 to 2026, with date and district filters.",
    learn: "How observed rainfall varied over time and across districts, and how complete the records are.",
  },
  {
    to: "/ml-experiment",
    title: "ML Experiment",
    what: "A retrospective feasibility study of machine-learning models on the available flood-impact labels.",
    learn: "Whether the current data are enough to support a reliable model. This is research, not a live tool.",
  },
  {
    to: "/about",
    title: "About & Method",
    what: "The data sources, assessment rules, class definitions and known limitations behind every page.",
    learn: "Exactly what each number means, what it does not mean, and where the data fall short.",
  },
  {
    to: "/scenario",
    title: "Hypothetical Scenario",
    what: "Type in a rainfall total and see how the fixed rules would rate it for a district.",
    learn: "How the rules respond to different totals. The input is typed by you; it is never an observation or a prediction.",
  },
];

const STEPS = [
  { t: "Rainfall observations", d: "Daily district-level rainfall records are collected and stored.", l: "Gaps stay gaps. Missing days are never turned into zero." },
  { t: "Historical flood impact", d: "Seasonal flood-impact records are organised by district and year.", l: "Annual records, not daily events. Some years are unknown." },
  { t: "District vulnerability", d: "Each district's historical impact is summarised into a seasonal class.", l: "Unknown where there are too few records." },
  { t: "Rule-based assessment", d: "Fixed rules compare rainfall with local history and combine it with vulnerability.", l: "Not validated as an operational warning." },
  { t: "Visualisation", d: "Maps, charts and tables show the results with their uncertainty.", l: "Unknown is always shown as Unknown." },
];

export function HomePage() {
  return (
    <div className="home">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-inner">
          <div>
            <span className="eyebrow">Capstone research project · Assam, India</span>
            <h1 id="hero-title">Understanding flood risk across Assam</h1>
            <p className="lead">
              Every monsoon, the Brahmaputra and its tributaries put communities, farmland and roads across Assam at risk. This platform brings together rainfall
              observations, historical flood impacts and district-level vulnerability so that patterns can be explored district by district.
            </p>
            <p className="lead">It is a tool for exploring and understanding the data, not for issuing warnings.</p>
            <div className="hero-actions">
              <Link to="/map" className="btn-primary">Open the risk map</Link>
              <Link to="/recent-rainfall" className="btn-outline-light">Explore rainfall records</Link>
              <Link to="/about" className="btn-outline-light">Read the methodology</Link>
            </div>
            <p className="hero-note">Academic prototype. Not an official flood-warning service and not a day-by-day prediction.</p>
          </div>
          <svg className="hero-art" viewBox="0 0 400 300" role="img" aria-label="Abstract motif of river channels over contour lines">
            <g fill="none" stroke="#2b6f87" strokeWidth="1">
              <ellipse cx="200" cy="150" rx="190" ry="130" opacity="0.35" />
              <ellipse cx="200" cy="150" rx="150" ry="100" opacity="0.4" />
              <ellipse cx="200" cy="150" rx="110" ry="72" opacity="0.5" />
              <ellipse cx="200" cy="150" rx="70" ry="44" opacity="0.6" />
            </g>
            <g fill="none" strokeLinecap="round">
              <path d="M10 190 C70 120 110 210 170 160 S270 110 330 150 S380 120 392 100" stroke="#5cc2cf" strokeWidth="5" />
              <path d="M90 40 C110 90 140 110 170 160" stroke="#3b9fb0" strokeWidth="2.5" />
              <path d="M300 30 C290 80 310 120 330 150" stroke="#3b9fb0" strokeWidth="2.5" />
              <path d="M200 270 C210 230 190 200 170 160" stroke="#3b9fb0" strokeWidth="2.5" />
            </g>
          </svg>
        </div>
      </section>

      <section className="band" aria-labelledby="why">
        <div>
          <span className="eyebrow">Context</span>
          <h2 id="why" style={{ marginTop: 0 }}>Why this project matters</h2>
          <div className="grid grid-2">
            <div>
              <p>
                Assam sits in the Brahmaputra valley, and floods recur there in most monsoon seasons. The Brahmaputra and its many tributaries carry heavy
                seasonal flows, and when they rise, the effects reach homes, schools, roads, crops and livestock.
              </p>
              <p>
                Floods affect communities unevenly. Two neighbouring districts can have very different histories, depending on terrain, river proximity and how
                often they are affected.
              </p>
            </div>
            <div>
              <p>
                That is why district-level analysis is useful: a statewide picture hides local differences. Looking at each district's own flood history and
                rainfall record shows where impacts have been reported, where rainfall has been unusual, and, importantly, where the data are too thin to say.
              </p>
              <p>
                Historical analysis also makes the limits of the evidence visible, which is the first step toward better monitoring.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="band band-alt" aria-labelledby="objectives">
        <div>
          <span className="eyebrow">Goals</span>
          <h2 id="objectives" style={{ marginTop: 0 }}>Project objectives</h2>
          <div className="grid grid-4">
            <div className="card"><h3>Organise the evidence</h3><p>Bring rainfall observations, flood-impact records and terrain data together at district level across all {DATA_FACTS.boundaryPolygons} districts.</p></div>
            <div className="card"><h3>Make patterns visible</h3><p>Present vulnerability, rainfall and history through maps and charts that can be read without specialist training.</p></div>
            <div className="card"><h3>Be honest about gaps</h3><p>Keep missing data as Unknown and explain coverage, so absence of data is never mistaken for absence of risk.</p></div>
            <div className="card"><h3>Test what ML can do</h3><p>Evaluate, as a separate experiment, whether the available labels can support a machine-learning model.</p></div>
          </div>
        </div>
      </section>

      <section className="band" aria-labelledby="how">
        <div>
          <span className="eyebrow">Workflow</span>
          <h2 id="how" style={{ marginTop: 0 }}>How the system works</h2>
          <p className="caption">From raw records to district-level views. Each step notes what it can and cannot tell you.</p>
          <ol className="steps">
            {STEPS.map((s) => (
              <li key={s.t}>
                <h3>{s.t}</h3>
                <p>{s.d}</p>
                <p className="step-limit">{s.l}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="band band-alt" aria-labelledby="explore">
        <div>
          <span className="eyebrow">Features</span>
          <h2 id="explore" style={{ marginTop: 0 }}>Explore the platform</h2>
          <div className="grid grid-3">
            {FEATURES.map((f) => (
              <Link key={f.to} to={f.to} className="card feature-card">
                <h3>{f.title}</h3>
                <p>{f.what}</p>
                <p className="learn"><strong>What you can learn:</strong> {f.learn}</p>
                <span className="go">Open →</span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="band" aria-labelledby="scope">
        <div>
          <span className="eyebrow">Scope</span>
          <h2 id="scope" style={{ marginTop: 0 }}>What this platform is, and what it is not</h2>
          <div className="compare">
            <div><span className="tagline">Monitoring</span><h3>Rainfall monitoring</h3><p>Shows rainfall that was recorded by district and date.</p><p><strong>Does not</strong> establish flooding, inundation or affected population.</p></div>
            <div><span className="tagline">History</span><h3>Historical flood impact</h3><p>Shows reported seasonal impact by district and year, where records exist.</p><p><strong>Does not</strong> describe individual days or events.</p></div>
            <div><span className="tagline">Assessment</span><h3>Vulnerability assessment</h3><p>Summarises each district's historical impact into a seasonal class.</p><p><strong>Does not</strong> predict what will happen next.</p></div>
            <div className="exp"><span className="tagline">Experimental</span><h3>Machine-learning study</h3><p>A retrospective test of whether the labels can support a model.</p><p><strong>Is not</strong> part of the map and produces no live results.</p></div>
          </div>
          <div className="info-note caution">
            <strong>Not a warning service.</strong>
            <p>
              This platform does not currently provide reliable daily or short-term flood predictions, and no trained model feeds the risk map. For official alerts,
              consult the Assam State Disaster Management Authority and the India Meteorological Department.
            </p>
          </div>
        </div>
      </section>

      <section className="band band-alt" aria-labelledby="coverage">
        <div>
          <span className="eyebrow">Data coverage</span>
          <h2 id="coverage" style={{ marginTop: 0 }}>What the data cover</h2>
          <p className="caption">Figures documented during data preparation. Coverage is incomplete, and the incompleteness is part of the story.</p>
          <div className="fact-row">
            <div className="stat-card"><span className="stat-label">Districts mapped</span><strong className="stat-value">{DATA_FACTS.boundaryPolygons}</strong></div>
            <div className="stat-card"><span className="stat-label">Flood-impact records</span><strong className="stat-value">{DATA_FACTS.districtYearRecords}</strong><span className="stat-sub">of {DATA_FACTS.possibleDistrictYears} possible district-years ({DATA_FACTS.labelYears})</span></div>
            <div className="stat-card"><span className="stat-label">Unknown district-years</span><strong className="stat-value">{DATA_FACTS.unknownDistrictYears}</strong><span className="stat-sub">shown as Unknown, never as zero</span></div>
            <div className="stat-card"><span className="stat-label">Rainfall stations</span><strong className="stat-value">{DATA_FACTS.rainfallStations}</strong><span className="stat-sub">covering {DATA_FACTS.rainfallDistricts} districts (station-based history)</span></div>
          </div>
        </div>
      </section>
    </div>
  );
}
