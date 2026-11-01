import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { ComponentBadge } from "../components/ComponentBadge";
import { ModelMetadataPanel } from "../components/ModelMetadataPanel";
import { Swatch } from "../components/MapPatterns";
import { CLASS_ORDER, CLASS_STYLE, DATA_FACTS } from "../constants";

export function AboutPage() {
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash]);

  return (
    <div className="page narrow prose">
      <h1>About this assessment</h1>

      <p className="lead">
        This dashboard is a <strong>seasonal, district-level flood-risk assessment</strong> for Assam, built as a college capstone project. It brings together how severe flood impacts have
        been in each district, what the terrain is like, and, where rainfall observations exist, how unusual recent rain is.
      </p>
      <aside className="disclaimer" role="note">
        <strong>What this is not.</strong> It is an academic prototype, not an official warning service. It does not predict whether a district will flood on a particular day, and nothing here
        should be used for safety decisions. For warnings, use the Assam State Disaster Management Authority and the India Meteorological Department.
      </aside>

      <h2>Why seasonal, not daily</h2>
      <p>
        The project first aimed at day-by-day prediction. The flood records we could collect are not daily: they are one impact per district per season. Seasonal records cannot support
        day-level statements, so the project assesses <strong>seasonal and annual</strong> risk instead.
      </p>

      <h2>The three parts of a district result</h2>
      <p>The district panel shows these separately. Only the first can come from a machine-learning model.</p>

      <section className="component-card">
        <header>
          <h3>District vulnerability</h3> <ComponentBadge type="ml_estimate" /> <ComponentBadge type="empirical_history" />
        </header>
        <p>
          The flood-impact class a district tends to have in a <em>normal</em> season, based on its terrain, population density and seasonal rainfall features. Where the training labels
          support it, a tree-based model estimates the class (Random Forest or XGBoost; logistic regression was an earlier baseline), with SHAP showing which features mattered. If the model
          does not beat simple baselines in cross-validation, the district's own historical mean class is used instead and no probabilities or SHAP are shown. The model section below says
          which is in use.
        </p>
      </section>

      <section className="component-card">
        <header>
          <h3>Rain hazard</h3> <ComponentBadge type="rule_based" />
        </header>
        <p>
          Adds up observed rain over a window (the backend offers a few lengths) and compares the total with the same district's own history for the same time of year. The level is how many of
          three historical thresholds the total exceeds. No model and no flood records are involved. It exists only where rainfall observations exist, and is Unknown elsewhere.
        </p>
      </section>

      <section className="component-card">
        <header>
          <h3>Combined risk category</h3> <ComponentBadge type="rule_based_combination" />
        </header>
        <p>
          A fixed rule that adds the vulnerability class and the hazard level. Because it needs both, it is Unknown wherever rain hazard is Unknown. Its score is an ordering index, not a
          probability, and the rule has <strong>not been validated against observed floods</strong>.
        </p>
      </section>

      <h2>Known, none reported, unknown</h2>
      <p>The historical flood-impact view keeps three situations apart, because they mean different things:</p>
      <ul>
        <li><strong>Known impact:</strong> the source reports an impact for that district and year.</li>
        <li><strong>No reported impact:</strong> the source explicitly reports none (shown with a dashed border).</li>
        <li><strong>Unknown:</strong> no usable record (grey, hatched). This is a data gap. It is not zero flooding and not Low risk.</li>
      </ul>
      <p>The map follows the same rule: a district with no assessment, or not enough data, is grey and is never counted as Low.</p>

      <h2>Reading the colours</h2>
      <ul className="legend-list">
        {[...CLASS_ORDER, "unknown" as const].map((c) => (
          <li key={c}>
            <Swatch cls={c} /> <strong>{CLASS_STYLE[c].label}</strong>: {CLASS_STYLE[c].pattern === "none" ? "plain fill" : `${CLASS_STYLE[c].pattern} pattern`}
          </li>
        ))}
      </ul>
      <p>Each class has its own colour, pattern and symbol, so the map can be read without relying on colour.</p>

      <h2>The data</h2>
      <ul>
        <li>
          <strong>District boundaries:</strong> {DATA_FACTS.boundaryPolygons} district polygons (EPSG:4326, some MultiPolygons). Bajali and Tamulpur are not separate polygons; their records were
          mapped to Barpeta and Baksa during preparation.
        </li>
        <li>
          <strong>Seasonal flood labels, {DATA_FACTS.labelYears}:</strong> {DATA_FACTS.sourceRecords} source records were combined into {DATA_FACTS.districtYearRecords} district-year records.
          There are {DATA_FACTS.possibleDistrictYears} possible district-years, so <strong>{DATA_FACTS.unknownDistrictYears} are unknown</strong>.
        </li>
        <li>
          <strong>Rainfall:</strong> station records from {DATA_FACTS.rainfallStations} stations covering only {DATA_FACTS.rainfallDistricts} of the {DATA_FACTS.boundaryPolygons} districts, with gaps.
          Missing days are treated as missing, never as zero. A CHIRPS v3 satellite extraction was written but its download was interrupted, so CHIRPS is not part of the current data.
        </li>
        <li>
          <strong>Terrain:</strong> Copernicus GLO-30 elevation, with valid coverage in all {DATA_FACTS.boundaryPolygons} districts. It is a digital surface model, so it includes buildings and
          vegetation.
        </li>
        <li>
          <strong>Population:</strong> a population raster exists, but its year and units are not yet verified, so population values are labelled unverified.
        </li>
        <li>
          <strong>Not used:</strong> there is no reliable land-cover dataset or river-gauge dataset in the project.
        </li>
      </ul>

      <h2>Known limitations</h2>
      <ul>
        <li>Labels are seasonal, so they say nothing about individual events or days.</li>
        <li>Missing labels are not interpreted as zero flooding or Low risk.</li>
        <li>Reporting periods differ between years, and some 2019 records are a fourth-wave snapshot rather than a complete season.</li>
        <li>The 2020 affected-population total does not reconcile with its source memo.</li>
        <li>Absolute affected-population counts favour large districts, so they are not compared across districts.</li>
        <li>Rainfall coverage is incomplete, so rain hazard and the combined category are Unknown for most districts.</li>
        <li>Without river-gauge or land-cover data, flooding driven by upstream rain or land use is not captured.</li>
        <li>With so few labelled district-years, model scores are noisy. Nothing here claims accuracy or operational readiness.</li>
      </ul>

      <h2>Rainfall scenarios</h2>
      <p>
        The Rainfall scenario page lets you type a hypothetical rain total and see how the fixed rules would rate it. It is illustrative, is clearly marked as such, and never appears on the map,
        overview or history.
      </p>

      <h2 id="model">The vulnerability model</h2>
      <p className="muted">
        Everything below is read from the backend as recorded when the model was trained. The scores describe cross-validation on a small label set and are not evidence that the model is
        ready for real-world use.
      </p>
      <ModelMetadataPanel />
    </div>
  );
}
