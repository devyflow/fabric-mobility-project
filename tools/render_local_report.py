"""Render a self-contained review report from a verified local build."""
import argparse
import base64
import csv
import html
import io
import json
import shutil
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--workspace", type=Path, required=True)
args = parser.parse_args()
pointer = json.loads((args.workspace / "latest_success.json").read_text(encoding="utf-8"))
run_dir = (args.workspace / pointer["path"]).resolve()
if not run_dir.is_relative_to(args.workspace.resolve()):
    raise ValueError("Build path escapes workspace")
run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
if run["status"] not in ("partial_success", "passed_locally"):
    raise ValueError("Only verified successful builds may be rendered")
output = ROOT / "reports"
output.mkdir(exist_ok=True)
data_output = output / "tables"
data_output.mkdir(exist_ok=True)
exported_files = sorted(run_dir.glob("*.csv"))
for file in exported_files:
    shutil.copy2(file, data_output / file.name)

con = duckdb.connect(str(run_dir / "analytics.duckdb"), read_only=True)
daily = con.execute("SELECT report_date,trip_count,avg_base_fare_usd,matched_charge_usd,matched_charge_eur FROM mobility_daily ORDER BY report_date").fetchall()
zone = con.execute("SELECT z.zone_name,sum(f.trip_count) AS n FROM fact_taxi_daily f JOIN dim_zone z ON f.pickup_zone_id=z.zone_id GROUP BY z.zone_name ORDER BY n DESC LIMIT 10").fetchall()
hourly = con.execute("SELECT pickup_hour,sum(trip_count) FROM taxi_hourly GROUP BY pickup_hour ORDER BY pickup_hour").fetchall()
gdp = con.execute("SELECT year,gdp_current_usd FROM dim_gdp ORDER BY year").fetchall()
rates = con.execute("SELECT report_date,usd_per_eur FROM dim_fx ORDER BY report_date").fetchall()
totals = con.execute("SELECT sum(trip_count),sum(base_fare_usd),sum(total_charged_usd),sum(total_charged_eur),sum(zero_distance_trip_count) FROM fact_taxi_daily").fetchone()
negatives = con.execute("SELECT count(*),sum(fare_usd) FROM reporting_taxi WHERE fare_usd < 0").fetchone()
def record(query, parameters=None):
    result = con.execute(query, parameters or [])
    return dict(zip([column[0] for column in result.description],result.fetchone()))
trace = record("""SELECT file_row_number, tpep_pickup_datetime, PULocationID,
    trip_distance, fare_amount, total_amount, pickup_date, pickup_hour,
    pickup_zone_id, fare_usd, total_charged_usd, quality_flags
    FROM reporting_taxi WHERE distance_miles=0 AND fare_usd>0
    ORDER BY file_row_number LIMIT 1""")
trace_payload = {"scope":"Actual public TLC record traced through local processing",
    "source_sha256":next(i['sha256'] for i in run['inputs'] if i['source']=='nyc_taxi'),
    "source_row_number_convention":"DuckDB file_row_number, zero-based within the original file",
    "source_and_silver":trace,
    "gold_group":record("SELECT * FROM fact_taxi_daily WHERE report_date=? AND pickup_zone_id=?",[trace['pickup_date'],trace['pickup_zone_id']]),
    "chosen_fx":record("SELECT * FROM dim_fx WHERE report_date=?",[trace['pickup_date']]),
    "explanation":"This retained source row contributes one trip and its recorded amounts to the date/zone total. A zero-distance flag does not remove its charges."}
(output/"trace_example.json").write_text(json.dumps(trace_payload,default=str,indent=2)+"\n",encoding="utf-8")
flags = con.execute("SELECT flag,count(*) AS affected_rows FROM silver_taxi,unnest(quality_flags) AS t(flag) GROUP BY flag ORDER BY affected_rows DESC").fetchall()
with (output/"quality_summary.csv").open("w",newline="",encoding="utf-8") as stream:
    writer=csv.writer(stream); writer.writerow(["flag","affected_rows"]); writer.writerows(flags)
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.titlesize":13,"axes.titleweight":"bold",
    "axes.spines.top":False,"axes.spines.right":False,"axes.labelcolor":"#334155","text.color":"#0f172a",
    "axes.edgecolor":"#cbd5e1","figure.facecolor":"#ffffff"})
blue, teal, amber = "#2856a6", "#087e8b", "#b26b13"
fig, ax = plt.subplots(2,2,figsize=(14,9.4),layout="constrained")
fig.suptitle("NYC Yellow Taxi — June 2025",fontsize=21,fontweight="bold",ha="left",x=.04)
dates, trips, avg, usd, eur = zip(*daily)
ax[0,0].plot(dates,trips,color=blue,linewidth=2)
ax[0,0].set(title="Recorded trips per day",ylabel="Trips")
ax[0,0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f"{v/1000:.0f}k"))
ax[0,0].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
ax[0,0].grid(axis="y",alpha=.16)
names, counts = zip(*reversed(zone))
ax[0,1].barh(names,counts,color=teal,height=.65)
ax[0,1].set(title="Ten busiest pickup zones",xlabel="Recorded trips")
ax[0,1].xaxis.set_major_formatter(FuncFormatter(lambda v,p:f"{v/1000:.0f}k"))
ax[1,0].bar([r[0] for r in hourly],[r[1] for r in hourly],color=blue,width=.78)
ax[1,0].set(title="Pickup hour across the month",xlabel="New York local hour",ylabel="Recorded trips",xticks=[0,6,12,18,23])
ax[1,0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f"{v/1000:.0f}k"))
ax[1,1].plot(dates,avg,color=amber,linewidth=2)
ax[1,1].set(title="Average recorded base fare",ylabel="USD per known fare")
ax[1,1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
ax[1,1].grid(axis="y",alpha=.16)
for axis in (ax[0,0], ax[1,1]):
    axis.xaxis.set_major_locator(mdates.DayLocator(interval=7))
    axis.set_xlim(dates[0], dates[-1])
fig.savefig(output/"mobility_overview.png",dpi=160)
plt.close(fig)

fig, ax = plt.subplots(1,3,figsize=(15,4.8),layout="constrained")
fig.suptitle("Taxi charges and economic context",fontsize=18,fontweight="bold",ha="left",x=.04)
ax[0].plot(dates,[float(v)/1e6 if v is not None else float('nan') for v in usd],label="USD",color=blue)
ax[0].plot(dates,[float(v)/1e6 if v is not None else float('nan') for v in eur],label="EUR",color=teal)
ax[0].set(title="Same charge records, two currencies",ylabel="Millions of currency units")
ax[0].xaxis.set_major_formatter(mdates.DateFormatter("%d %b")); ax[0].legend(frameon=False)
ax[1].plot([r[0] for r in rates],[float(r[1]) if r[1] is not None else float('nan') for r in rates],color=teal)
ax[1].set(title="Effective reference rate",ylabel="USD per EUR")
ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
ax[2].bar([str(r[0]) for r in gdp],[float(r[1])/1e12 if r[1] is not None else float('nan') for r in gdp],color=blue,width=.55)
ax[2].set(title="US nominal GDP — annual context",ylabel="Trillion current USD")
for axis in (ax[0], ax[1]):
    axis.xaxis.set_major_locator(mdates.DayLocator(interval=7))
    axis.set_xlim(dates[0], dates[-1])
fig.savefig(output/"economic_context.png",dpi=160)
plt.close(fig)

air_chart_names = []
if run["openaq"]["status"] == "passed":
    rows = con.execute("SELECT report_date,location_id,pollutant_code,measurement_unit,concentration_mean FROM fact_air_quality_daily ORDER BY ALL").fetchall()
    groups = {}
    for day, station, pollutant, unit, value in rows:
        groups.setdefault((station,pollutant,unit),[]).append((day,value))
    for index, (pollutant, unit) in enumerate(sorted({(key[1],key[2]) for key in groups})):
        fig, ax = plt.subplots(figsize=(12,5),layout="constrained")
        for key, values in groups.items():
            if key[1:] == (pollutant,unit):
                ax.plot([v[0] for v in values],[v[1] for v in values],label=f"Station {key[0]}")
        ax.set(title=f"Daily station {pollutant}",ylabel=unit); ax.legend(frameon=False)
        filename = f"air_quality_{index:02d}.png"
        fig.savefig(output/filename,dpi=160); plt.close(fig)
        air_chart_names.append(filename)
    air_message = "Real station observations are shown separately by pollutant/unit. Inspect observed-hour counts and matched-day counts in the exported tables. Correlation summaries describe association, not causation."
else:
    air_message = "Air quality and taxi–pollution correlation are awaiting authenticated OpenAQ observations and reviewed geography. No environmental result has been estimated or fabricated."

def image_tag(name, alt):
    encoded = base64.b64encode((output/name).read_bytes()).decode()
    return f'<img alt="{html.escape(alt)}" src="data:image/png;base64,{encoded}">'
v = run["validation"]
rows = "".join(f'<tr><td>{html.escape(c["name"].replace("_"," "))}</td><td>Passed</td></tr>' for c in v["checks"])
links = "".join(f'<li><a href="tables/{f.name}">{f.stem.replace("_"," ")}</a></li>' for f in exported_files)
air_images = "".join(image_tag(name,"Measured station air quality in a single pollutant and unit") for name in air_chart_names)
document = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fabric project local verification report</title>
<style>body{{font:17px/1.6 system-ui,sans-serif;color:#172033;background:#f1f5f9;margin:0}}main{{max-width:1140px;margin:auto;padding:44px 30px;background:white}}h1{{font-size:38px;line-height:1.15;max-width:850px}}h2{{margin-top:38px}}p{{max-width:920px}}.eyebrow{{font-size:13px;letter-spacing:.1em;color:#2856a6;font-weight:700}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin:30px 0}}.metric strong{{font-size:30px;display:block}}.metric span{{font-size:14px;color:#475569}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:15px}}td,th{{border-bottom:1px solid #dbe3ee;padding:9px;text-align:left}}summary{{cursor:pointer;font-weight:700}}a{{color:#2856a6}}.note{{color:#475569}}@media(max-width:700px){{main{{padding:24px 16px}}h1{{font-size:29px}}.metrics{{grid-template-columns:1fr}}}}@media print{{body{{background:white}}main{{padding:0}}details{{display:block}}}}</style>
<main><p class="eyebrow">VERIFIED LOCAL BUILD · FABRIC DEPLOYMENT PENDING</p>
<h1>Mobility, currency conversion and a traceable data journey</h1>
<p>NYC Yellow Taxi records for {run['reporting_start']} to {run['reporting_end']}. These charts use real TLC, ECB and World Bank source data. This report demonstrates local business-rule verification; it is not evidence of a successful Fabric run.</p>
<div class="metrics"><div class="metric"><strong>{totals[0]:,}</strong><span>trips with pickups inside June</span></div><div class="metric"><strong>${totals[2]:,.2f}</strong><span>recorded total charges, including negative entries</span></div><div class="metric"><strong>{totals[4]:,}</strong><span>zero-distance trips retained</span></div></div>
<h2>1. Mobility</h2>{image_tag('mobility_overview.png','Trips by day, pickup zone and hour, plus average base fare')}
<p>Recorded charges are source financial fields, not verified company revenue. Negative fares remain included and visible; {negatives[0]:,} June records have negative base fares totalling ${negatives[1]:,.2f}. These require interpretation rather than automatic deletion.</p>
<h2>2. Currency and annual context</h2>{image_tag('economic_context.png','Matched USD and EUR charges, effective rates and annual US GDP')}
<p>EUR = USD ÷ USD per EUR. Weekends use the latest preceding published rate, at most seven days old. There are {v['uncovered_fx_dates']} uncovered dates. USD and EUR use the same eligible charge records. GDP is national, annual and nominal; it does not measure NYC output or prove a mobility–growth relationship.</p>
<h2>3. Air quality and cross-domain comparison</h2><p>{html.escape(air_message)}</p>{air_images}
<h2>4. Reconciliation and recovery</h2><p>All {v['source_rows']:,} source records remain in Silver. {v['reporting_rows']:,} have pickup dates inside the reporting window. {v['outside_reporting_window_rows']:,} are outside it, and {v['missing_pickup_date_rows']:,} lack a usable pickup date. Excluded reporting records remain traceable in detailed data.</p>
<p>Same-input rerun: {html.escape(run.get('same_input_rerun','not requested'))}. The build publishes its latest-success pointer only after validation passes.</p>
<details><summary>Inspect validation checks</summary><table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></details>
<h2>5. Walk through the implementation</h2><ol><li>Inspect source schemas and checksums.</li><li>Retain raw source versions in Bronze.</li><li>Standardize fields and flag unusual records in Silver.</li><li>Build daily/date/zone aggregates and calendar FX mappings in Gold.</li><li>Reconcile counts and money, rerun, then publish.</li><li>Deploy the corresponding notebooks, Dataflows and reporting schema to Fabric when capacity works.</li></ol>
<p><a href="../docs/walkthrough.md">Project explanation notes</a> · <a href="../docs/requirements.md">Requirement checklist</a> · <a href="local_build.json">Run evidence</a> · <a href="trace_example.json">Follow one real record</a> · <a href="quality_summary.csv">Quality flag counts</a></p>
<details><summary>Download reporting tables</summary><ul>{links}</ul></details>
<p class="note">Run {run['run_id']} · completed {run['completed_at_utc']} · Development scope is one month. Seasonal and multi-year conclusions require more overlapping history. Aggregate EUR values are rounded to four decimal places per date/zone.</p>
<p class="note">Sources: <a href="https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page">NYC TLC</a>, <a href="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html">ECB</a>, <a href="https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json">World Bank</a>. Retrieval metadata and SHA-256 checksums appear in the run evidence.</p></main></html>'''
(output/"project_report.html").write_text(document,encoding="utf-8")
con.close()
print(f"Rendered report and charts from verified run {run['run_id']}")
