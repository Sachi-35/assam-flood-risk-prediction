import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { Swatch } from "../components/MapPatterns";
import { InfoNote, PageHeader } from "../components/ui";
import { CLASS_ORDER, CLASS_STYLE, DATA_FACTS } from "../constants";

const TOC = [
  ["overview", "Overview"],
  ["workflow", "How the data flow"],
  ["model", "How the assessment works"],
  ["roles", "The four data roles"],
  ["missing", "Missing information"],
  ["colours", "Map colours"],
  ["data", "Data used"],
  ["rainfall", "Recent rainfall"],
  ["limitations", "Limitations"],
  ["objective", "Objective"],
] as const;

export function AboutPage() {
  const { hash } = useLocation();

  useEffect(() => {
    if (hash) {
      document.getElementById(hash.slice(1))?.scrollIntoView();
    }
  }, [hash]);

  return (
    <div className="page">
      <PageHeader eyebrow="Research · Methodology" title="About this project">
        An academic capstone project that brings together historical seasonal flood impacts and observed rainfall to give a district-level view of flood-related
        conditions across Assam, and that is explicit about what the data can and cannot support.
      </PageHeader>

      <div className="about-layout">
        <nav className="toc" aria-label="On this page">
          <strong>On this page</strong>
          <ol>
            {TOC.map(([id, label]) => (
              <li key={id}><a href={`#${id}`}>{label}</a></li>
            ))}
          </ol>
        </nav>

        <div className="about-body">
          <InfoNote variant="caution" title="Academic prototype only">
            <p>
              This application is not an official flood-warning service. It does not predict floods on individual days and must not be used to make safety or
              evacuation decisions. Refer to the Assam State Disaster Management Authority and the India Meteorological Department for official information.
            </p>
          </InfoNote>

          <section id="overview">
            <h2>Project overview</h2>
            <p>
              Flooding is influenced by several factors, including rainfall, geographical conditions and the history of flood impacts. This project organises
              available information at district level, across all {DATA_FACTS.boundaryPolygons} districts of Assam, to help explore these patterns.
            </p>
            <p>
              It is an academic prototype for seasonal and annual district-level flood-risk assessment. It does not provide official flood warnings, and no trained
              machine-learning model is part of the displayed assessment.
            </p>
          </section>

          <section id="workflow">
            <h2>How the data flow through the system</h2>
            <div className="flow" aria-label="Data flow diagram">
              <div><strong>Rainfall observations</strong>Daily district records</div>
              <span aria-hidden="true">→</span>
              <div><strong>Rain hazard</strong>Rainfall vs the district's own history</div>
              <span aria-hidden="true">→</span>
              <div><strong>Combined category</strong>Rule combining hazard and vulnerability</div>
              <span aria-hidden="true">→</span>
              <div><strong>Risk map</strong>Colours, patterns, Unknown</div>
            </div>
            <div className="flow">
              <div><strong>Flood-impact records</strong>Seasonal, by district and year</div>
              <span aria-hidden="true">→</span>
              <div><strong>Vulnerability</strong>Historical class per district</div>
              <span aria-hidden="true">→</span>
              <div><strong>Combined category</strong>(as above)</div>
            </div>
            <div className="flow">
              <div className="not-linked"><strong>ML feasibility experiment</strong>Tests whether the labels can support a model. Runs separately and is not connected to the map. See <Link to="/ml-experiment">ML Experiment</Link>.</div>
            </div>
          </section>

          <section id="model">
            <h2>How the assessment works</h2>

            <div className="component-card">
              <header>
                <h3>1. Historical flood vulnerability</h3>
                <span className="badge badge-empirical_history">Historical data</span>
              </header>
              <p>
                The current implementation uses an empirical historical approach based on reported seasonal flood-impact records for each district. It summarises
                the available history rather than generating a machine-learning prediction.
              </p>
              <p>
                Districts with insufficient historical records remain Unknown. Terrain information is available in the project dataset but is not currently used
                in this vulnerability calculation.
              </p>
            </div>

            <div className="component-card">
              <header>
                <h3>2. Observed rainfall hazard</h3>
                <span className="badge badge-rule_based">Rule-based</span>
              </header>
              <p>
                Where sufficient historical rainfall observations and matching district-specific climatology are available, accumulated rainfall over a selected 3,
                7, 15 or 30-day window is compared with historical thresholds for the same time of year.
              </p>
              <p>
                The hazard level depends on how many of three thresholds are exceeded. Districts without sufficient observations or matching historical thresholds
                remain Unknown.
              </p>
              <p>
                <strong>Illustrative placeholder.</strong> If the backend supplies a rainfall total for a window but no climatology-based level, the map shows a
                placeholder rating from fixed display thresholds (up to 25 mm Low, up to 50 mm Moderate, up to 100 mm High, above that Severe). These thresholds are
                not calibrated and the rating is always labelled as illustrative.
              </p>
            </div>

            <div className="component-card">
              <header>
                <h3>3. Combined assessment</h3>
                <span className="badge badge-rule_based_combination">Rule-based combination</span>
              </header>
              <p>
                The combined category uses the available vulnerability and rainfall hazard results. Both components are required, so the combined assessment
                remains Unknown when either component is unavailable. Where it is a placeholder, it takes the higher of the vulnerability class and the illustrative
                hazard, and is labelled accordingly.
              </p>
              <p>This category is an assessment index, not a probability of flooding, and has not been validated as an operational warning.</p>
            </div>
          </section>

          <section id="roles">
            <h2>The four data roles</h2>
            <div className="grid grid-2">
              <div className="card"><h3>Rainfall observations</h3><p>Show how much rain was recorded, by district and date. They do not show whether any land was flooded.</p></div>
              <div className="card"><h3>Historical flood-impact labels</h3><p>Seasonal records of reported impact by district and year. They are the basis of the vulnerability class and the only source of "what happened".</p></div>
              <div className="card"><h3>District vulnerability</h3><p>A summary of each district's own history. It reflects the past and says nothing about the coming season.</p></div>
              <div className="card"><h3>ML feasibility evaluation</h3><p>A separate retrospective test of whether the labels can support a model. Its models are not used on the map.</p></div>
            </div>
          </section>

          <section id="missing">
            <h2>Understanding missing information</h2>
            <p>Data availability varies across districts and years. The application keeps missing information separate from recorded values.</p>
            <ul>
              <li><strong>Reported:</strong> a usable historical flood-impact record is available.</li>
              <li><strong>No reported impact:</strong> the source explicitly records no impact.</li>
              <li><strong>Unknown:</strong> there is no usable record or insufficient data to calculate an assessment.</li>
            </ul>
            <p>Unknown does not mean zero rainfall, no flooding or low risk. Missing observations are never automatically treated as zero. A recorded 0.0 mm is a real observed zero.</p>
          </section>

          <section id="colours">
            <h2>Understanding the map colours</h2>
            <ul className="legend-list">
              {[...CLASS_ORDER, "unknown" as const].map((c) => (
                <li key={c}>
                  <Swatch cls={c} />
                  <strong>{CLASS_STYLE[c].label}</strong>: {CLASS_STYLE[c].pattern === "none" ? "plain fill" : `${CLASS_STYLE[c].pattern} pattern`}
                </li>
              ))}
            </ul>
            <p>Colours, patterns and symbols help distinguish assessment categories. Grey and hatched areas indicate unavailable information, not low risk.</p>
          </section>

          <section id="data">
            <h2>Data used in the project</h2>
            <ul>
              <li><strong>District boundaries:</strong> {DATA_FACTS.boundaryPolygons} district polygons organise the geographical view. Bajali and Tamulpur are not separate polygons in the boundary dataset.</li>
              <li>
                <strong>Historical flood impact:</strong> {DATA_FACTS.sourceRecords} source records were organised into {DATA_FACTS.districtYearRecords} district-year records across{" "}
                {DATA_FACTS.labelYears}. Of {DATA_FACTS.possibleDistrictYears} possible district-years, {DATA_FACTS.unknownDistrictYears} are unknown.
              </li>
              <li>
                <strong>Historical rainfall:</strong> station observations from {DATA_FACTS.rainfallStations} stations cover {DATA_FACTS.rainfallDistricts} districts. Coverage is
                incomplete, and missing days remain missing.
              </li>
              <li>
                <strong>Terrain:</strong> Copernicus GLO-30 elevation information has been processed for all {DATA_FACTS.boundaryPolygons} district areas. It is supporting project data and
                is not currently used in the vulnerability calculation.
              </li>
            </ul>
          </section>

          <section id="rainfall">
            <h2>Recent rainfall observations</h2>
            <p>
              The <Link to="/recent-rainfall">Recent Rainfall</Link> page presents one combined district-day rainfall dataset covering 2019 to 2026. It is a separate observational view:
              these measurements are not fed into the historical assessment or presented as a flood prediction.
            </p>
            <ul>
              <li>With all districts selected, the daily chart shows the <strong>mean</strong> across districts that have a recorded value on each date, not a sum.</li>
              <li>"Cumulative district-day rainfall" is the sum of recorded district-day measurements. It is not a statewide rainfall total.</li>
              <li>Dates without a record are not filled with zero.</li>
            </ul>
          </section>

          <section id="limitations">
            <h2>Project limitations</h2>
            <ul>
              <li>Historical flood-impact records are seasonal or annual, not daily event records.</li>
              <li>Reporting periods vary between years, and some records represent partial reporting periods.</li>
              <li>Historical rainfall observations cover only a subset of districts and contain gaps.</li>
              <li>Rainfall hazard requires sufficient observations and matching historical climatology.</li>
              <li>The combined category is rule-based and has not been validated against observed future flood events.</li>
              <li>Rainfall measurements alone do not establish inundation, flood occurrence or affected population.</li>
              <li>A trained machine-learning model is not currently integrated into the displayed assessment.</li>
            </ul>
          </section>

          <section id="objective">
            <h2>Project objective</h2>
            <p>
              The objective is to demonstrate how historical flood-impact records, rainfall observations and geographical information can be organised into an
              understandable district-level assessment, while clearly communicating data coverage and uncertainty.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
