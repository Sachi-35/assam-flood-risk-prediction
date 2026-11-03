import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { Swatch } from "../components/MapPatterns";
import { CLASS_ORDER, CLASS_STYLE, DATA_FACTS } from "../constants";

export function AboutPage() {
  const { hash } = useLocation();

  useEffect(() => {
    if (hash) {
      document.getElementById(hash.slice(1))?.scrollIntoView();
    }
  }, [hash]);

  return (
    <div className="page narrow prose">
      <h1>About this project</h1>

      <p className="lead">
        The Assam Flood Risk Assessment is an academic capstone project that
        brings together historical seasonal flood impacts and observed rainfall
        information to provide a district-level view of flood-related conditions
        across Assam.
      </p>

      <aside className="disclaimer" role="note">
        <strong>Academic prototype only.</strong> This application is not an
        official flood-warning service. It does not predict floods on individual
        days and must not be used to make safety or evacuation decisions.
        Refer to the Assam State Disaster Management Authority and the India
        Meteorological Department for official information.
      </aside>

      <h2>Project overview</h2>
      <p>
        Flooding is influenced by several factors, including rainfall,
        geographical conditions and the history of flood impacts. This project
        organizes available information at the district level to help explore
        these patterns.
      </p>
      <p>
        This project is an academic prototype for seasonal and annual district-level flood-risk assessment. It does not provide official flood warnings.
      </p>

      <h2>How the assessment works</h2>

      <section className="component-card">
        <header>
          <h3>1. Historical flood vulnerability</h3>
          <span className="badge badge-empirical_history">
            Historical data
          </span>
        </header>
        <p>
          The current implementation uses an empirical historical approach
          based on reported seasonal flood-impact records for each district.
          It summarizes the available history rather than generating a
          machine-learning prediction.
        </p>
        <p>
          Districts with insufficient historical records remain Unknown.
          Terrain information is available in the project dataset but is not
          currently used in this vulnerability calculation.
        </p>
      </section>

      <section className="component-card">
        <header>
          <h3>2. Observed rainfall hazard</h3>
          <span className="badge badge-rule_based">Rule-based</span>
        </header>
        <p>
          Where sufficient historical rainfall observations and matching
          district-specific climatology are available, accumulated rainfall
          over a selected 3, 7, 15 or 30-day window is compared with historical
          thresholds for the same time of year.
        </p>
        <p>
          The hazard level depends on how many of three thresholds are
          exceeded. Districts without sufficient observations or matching
          historical thresholds remain Unknown.
        </p>
      </section>

      <section className="component-card">
        <header>
          <h3>3. Combined assessment</h3>
          <span className="badge badge-rule_based_combination">
            Rule-based combination
          </span>
        </header>
        <p>
          The combined category uses the available vulnerability and rainfall
          hazard results. Both components are required, so the combined
          assessment remains Unknown when either component is unavailable.
        </p>
        <p>
          This category is an assessment index, not a probability of flooding,
          and has not been validated as an operational warning.
        </p>
      </section>

      <h2>Understanding missing information</h2>
      <p>
        Data availability varies across districts and years. The application
        keeps missing information separate from recorded values.
      </p>
      <ul>
        <li>
          <strong>Reported:</strong> a usable historical flood-impact record
          is available.
        </li>
        <li>
          <strong>No reported impact:</strong> the source explicitly records
          no impact.
        </li>
        <li>
          <strong>Unknown:</strong> there is no usable record or insufficient
          data to calculate an assessment.
        </li>
      </ul>
      <p>
        Unknown does not mean zero rainfall, no flooding or low risk. Missing
        observations are never automatically treated as zero.
      </p>

      <h2>Understanding the map colours</h2>
      <ul className="legend-list">
        {[...CLASS_ORDER, "unknown" as const].map((c) => (
          <li key={c}>
            <Swatch cls={c} />
            <strong>{CLASS_STYLE[c].label}</strong>:{" "}
            {CLASS_STYLE[c].pattern === "none"
              ? "plain fill"
              : `${CLASS_STYLE[c].pattern} pattern`}
          </li>
        ))}
      </ul>
      <p>
        Colours, patterns and symbols help distinguish assessment categories.
        Grey and hatched areas indicate unavailable information, not low risk.
      </p>

      <h2>Data used in the project</h2>
      <ul>
        <li>
          <strong>District boundaries:</strong>{" "}
          {DATA_FACTS.boundaryPolygons} district polygons are used to organize
          the geographical view. Bajali and Tamulpur are not separate polygons
          in the boundary dataset.
        </li>
        <li>
          <strong>Historical flood impact:</strong>{" "}
          {DATA_FACTS.sourceRecords} source records were organized into{" "}
          {DATA_FACTS.districtYearRecords} district-year records across{" "}
          {DATA_FACTS.labelYears}. Of{" "}
          {DATA_FACTS.possibleDistrictYears} possible district-years,{" "}
          {DATA_FACTS.unknownDistrictYears} are unknown.
        </li>
        <li>
          <strong>Historical rainfall:</strong> station observations from{" "}
          {DATA_FACTS.rainfallStations} stations cover{" "}
          {DATA_FACTS.rainfallDistricts} districts. Coverage is incomplete,
          and missing days remain missing.
        </li>
        <li>
          <strong>Terrain:</strong> Copernicus GLO-30 elevation information
          has been processed for all{" "}
          {DATA_FACTS.boundaryPolygons} district areas. It is available as
          supporting project data but is not currently used in the
          vulnerability calculation.
        </li>
      </ul>

      <h2>Recent rainfall observations</h2>
      <p>
        The Recent Rainfall page displays daily actual rainfall observations
        from the IMD district-wise dataset for the available 2026 period.
        This is a separate observational view. These recent measurements are
        not fed into the historical assessment or presented as a flood
        prediction.
      </p>

      <h2>Project limitations</h2>
      <ul>
        <li>
          Historical flood-impact records are seasonal or annual, not
          daily event records.
        </li>
        <li>
          Reporting periods vary between years, and some records represent
          partial reporting periods.
        </li>
        <li>
          Historical rainfall observations cover only a subset of districts
          and contain gaps.
        </li>
        <li>
          Rainfall hazard requires sufficient observations and matching
          historical climatology.
        </li>
        <li>
          The combined category is rule-based and has not been validated
          against observed future flood events.
        </li>
        <li>
          A trained machine-learning model is not currently integrated into
          the displayed assessment.
        </li>
      </ul>

      <h2>Project objective</h2>
      <p>
        The objective is to demonstrate how historical flood-impact records,
        rainfall observations and geographical information can be organized
        into an understandable district-level assessment, while clearly
        communicating data coverage and uncertainty.
      </p>
    </div>
  );
}
