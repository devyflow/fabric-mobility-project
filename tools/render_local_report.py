"""Render a self-contained review report from a verified local build."""
import argparse
import base64
import csv
import html
import io
import json
import shutil
from datetime import date
from pathlib import Path
from statistics import mean

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--comparison-workspace", type=Path, help="Verified run for the same month in an earlier year")
args = parser.parse_args()


def read_build(workspace):
    pointer = json.loads((workspace / "latest_success.json").read_text(encoding="utf-8"))
    directory = (workspace / pointer["path"]).resolve()
    if not directory.is_relative_to(workspace.resolve()):
        raise ValueError("Build path escapes workspace")
    evidence = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if evidence["run_id"] != pointer["run_id"] or evidence["status"] not in ("partial_success", "passed_locally"):
        raise ValueError("Only verified successful builds may be rendered")
    return directory, evidence


run_dir, run = read_build(args.workspace)
report_start = date.fromisoformat(run["reporting_start"])
period = report_start.strftime("%B %Y")
comparison = read_build(args.comparison_workspace) if args.comparison_workspace else None
output = ROOT / "reports"
output.mkdir(exist_ok=True)
data_output = output / "tables"
data_output.mkdir(exist_ok=True)
shutil.copy2(run_dir / "run.json", output / "local_build.json")
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
zero_distance_charges = con.execute("""
    SELECT coalesce(sum(total_charged_usd), 0)
    FROM reporting_taxi WHERE distance_miles = 0
""").fetchone()[0]
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
trace_zone = record("SELECT zone_name FROM dim_zone WHERE zone_id=?", [trace["pickup_zone_id"]])["zone_name"]
(output/"trace_example.json").write_text(json.dumps(trace_payload,default=str,indent=2)+"\n",encoding="utf-8")
flags = con.execute("SELECT flag,count(*) AS affected_rows FROM silver_taxi,unnest(quality_flags) AS t(flag) GROUP BY flag ORDER BY affected_rows DESC").fetchall()
with (output/"quality_summary.csv").open("w",newline="",encoding="utf-8") as stream:
    writer=csv.writer(stream); writer.writerow(["flag","affected_rows"]); writer.writerows(flags)
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.titlesize":13,"axes.titleweight":"bold",
    "axes.spines.top":False,"axes.spines.right":False,"axes.labelcolor":"#334155","text.color":"#0f172a",
    "axes.edgecolor":"#cbd5e1","figure.facecolor":"#ffffff"})
blue, teal, amber = "#2856a6", "#087e8b", "#b26b13"
fig, ax = plt.subplots(2,2,figsize=(14,9.4),layout="constrained")
fig.suptitle(f"NYC Yellow Taxi — {period}",fontsize=21,fontweight="bold",ha="left",x=.04)
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

air_charts = []
correlation_table = ""
pollutant_names = {"pm25": "PM2.5", "o3": "Ozone"}
if run["openaq"]["status"] == "passed":
    policy = run["openaq"]["min_hours_for_pair"]
    station_names = dict(con.execute("SELECT location_id, station_name FROM dim_air_location").fetchall())
    zone_names = dict(con.execute("SELECT zone_id, zone_name FROM dim_zone").fetchall())
    rows = con.execute("""SELECT report_date,location_id,pollutant_code,measurement_unit,concentration_mean,observed_hour_count
        FROM fact_air_quality_daily ORDER BY ALL""").fetchall()
    groups = {}
    for day, station, pollutant, unit, value, hours in rows:
        groups.setdefault((station,pollutant,unit),{})[day] = (value, hours)
    colors = (blue, teal, amber)
    station_colors = {station: colors[i % len(colors)] for i, station in enumerate(sorted(station_names))}
    zone_colors = {station["zone_id"]: station_colors[station["location_id"]] for station in run["openaq"]["stations"]}
    for index, (pollutant, unit) in enumerate(sorted({(key[1],key[2]) for key in groups})):
        label = pollutant_names.get(pollutant, pollutant)
        fig, (trend, coverage) = plt.subplots(2, 1, figsize=(12, 6.6), sharex=True, layout="constrained",
                                               height_ratios=(2, 1))
        for (station, species, measurement_unit), values in groups.items():
            if (species, measurement_unit) != (pollutant, unit):
                continue
            concentration = [values[d][0] if d in values else float("nan") for d in dates]
            hours = [values[d][1] if d in values else 0 for d in dates]
            trend.plot(dates, concentration, label=station_names[station], color=station_colors[station])
            coverage.plot(dates, hours, color=station_colors[station], alpha=.8, marker=".", markersize=4)
        trend.set(title=f"Daily {label} at reviewed monitoring stations", ylabel=unit)
        trend.legend(frameon=False, ncols=2)
        coverage.axhline(policy, color="#64748b", linestyle="--", linewidth=1, label=f"{policy} hours to pair with taxi")
        coverage.legend(frameon=False, loc="lower left")
        coverage.set(ylabel="Observed hours", ylim=(0, 26))
        coverage.set_xlim(dates[0], dates[-1])
        coverage.set_xticks(dates[::7])
        coverage.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        filename = f"air_quality_{index:02d}.png"
        fig.savefig(output/filename,dpi=160)
        plt.close(fig)
        air_charts.append((filename, f"Daily {pollutant} in {unit} and hourly coverage for each station"))
    pairs = con.execute("""SELECT pickup_zone_id,pollutant_code,measurement_unit,trip_count,concentration
        FROM matched_air_taxi ORDER BY report_date,pickup_zone_id,pollutant_code,measurement_unit""").fetchall()
    summaries = con.execute("""SELECT pickup_zone_id,pollutant_code,measurement_unit,matched_days,pearson_r
        FROM air_taxi_correlation ORDER BY pollutant_code,measurement_unit,pickup_zone_id""").fetchall()
    pair_groups = {}
    for zone_id, pollutant, unit, count, concentration in pairs:
        pair_groups.setdefault((pollutant, unit, zone_id), []).append((count, concentration))
    series = sorted({key[:2] for key in pair_groups})
    point_markers = {zone_id: ("o", "^", "s")[index % 3] for index, zone_id in enumerate(sorted({p[0] for p in pairs}))}
    for index, (pollutant, unit) in enumerate(series):
        label = pollutant_names.get(pollutant, pollutant)
        fig, axis = plt.subplots(figsize=(9, 4.8), layout="constrained")
        for (species, measurement_unit, zone_id), points in pair_groups.items():
            if (species, measurement_unit) == (pollutant, unit):
                counts, concentrations = zip(*points)
                axis.scatter(counts, concentrations, label=zone_names[zone_id], color=zone_colors.get(zone_id, blue),
                             marker=point_markers[zone_id], alpha=.7)
        axis.set(title=f"Daily taxi pickups and {label}", xlabel="Recorded pickups that day", ylabel=unit)
        axis.legend(frameon=False, loc="upper center", bbox_to_anchor=(.5, -.20), ncols=3)
        filename = f"taxi_air_pairs_{index:02d}.png"
        fig.savefig(output/filename,dpi=160)
        plt.close(fig)
        air_charts.append((filename, f"Scatterplot of trips and {pollutant} in {unit} by day and zone"))
    rows = []
    for zone_id, pollutant, unit, count, coefficient in summaries:
        r_label = f"{coefficient:.3f}" if coefficient is not None else "Insufficient variation or days"
        label = pollutant_names.get(pollutant, pollutant)
        rows.append(f"<tr><td>{html.escape(zone_names[zone_id])}</td><td>{html.escape(label)} ({html.escape(unit)})</td>"
                    f"<td>{count}</td><td>{r_label}</td></tr>")
    correlation_table = ("<table><caption>Within-zone associations for the reporting month</caption><thead><tr>"
        "<th>Pickup zone</th><th>Pollutant (unit)</th><th>Matched days</th><th>Pearson r</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>")
    if pairs:
        air_trace = record("""SELECT t.*, z.zone_name FROM matched_air_taxi t
            JOIN dim_zone z ON t.pickup_zone_id=z.zone_id
            ORDER BY (t.pollutant_code='pm25') DESC, t.report_date, t.trip_count DESC,
                     t.pickup_zone_id, t.pollutant_code, t.measurement_unit LIMIT 1""")
        trace_payload["air_taxi_pair"] = air_trace
        trace_payload["air_station_day"] = record("""SELECT f.*, l.station_name FROM fact_air_quality_daily f
            JOIN dim_air_location l USING(location_id)
            WHERE f.report_date=? AND l.zone_id=? AND f.pollutant_code=? AND f.measurement_unit=?
            ORDER BY f.observed_hour_count DESC, f.location_id LIMIT 1""", [
                air_trace["report_date"], air_trace["pickup_zone_id"], air_trace["pollutant_code"], air_trace["measurement_unit"]])
        (output/"trace_example.json").write_text(json.dumps(trace_payload,default=str,indent=2)+"\n",encoding="utf-8")
    source = "OpenAQ public archive" if run["openaq"]["source_mode"] == "public_archive" else "OpenAQ API"
    air_message = (f"{source} readings are charted by pollutant and unit. An air day needs {policy} observed hours to pair "
        "with taxi trips. Each scatter point represents one date and zone. Pearson r is a descriptive association. "
        "Station coverage, weather, regional smoke and other conditions can influence the patterns.")
else:
    air_message = "Air analysis is awaiting a verified OpenAQ capture and reviewed station geography."


def comparison_section(previous_dir, previous):
    previous_start = date.fromisoformat(previous["reporting_start"])
    current_end = date.fromisoformat(run["reporting_end"])
    previous_end = date.fromisoformat(previous["reporting_end"])
    if (previous_start.year >= report_start.year or previous_start.strftime("%m-%d") != report_start.strftime("%m-%d")
            or previous_end.strftime("%m-%d") != current_end.strftime("%m-%d")):
        raise ValueError("Comparison must cover the same calendar dates in an earlier year")
    previous_label = previous_start.strftime("%B %Y")
    previous_trips = previous["validation"]["reporting_rows"]
    if not previous_trips:
        raise ValueError("Comparison must contain taxi trips")
    delta = (totals[0] / previous_trips - 1) * 100
    air_table = ""
    if previous["openaq"]["status"] == "passed" and run["openaq"]["status"] == "passed":
        policy = run["openaq"]["min_hours_for_pair"]
        if previous["openaq"]["min_hours_for_pair"] != policy:
            raise ValueError("Comparison periods must use the same coverage threshold")
        query = """SELECT location_id,pollutant_code,measurement_unit,day(report_date),concentration_mean
                   FROM fact_air_quality_daily WHERE observed_hour_count >= ?"""
        with duckdb.connect(str(previous_dir / "analytics.duckdb"), read_only=True) as old_db:
            old_days = {tuple(row[:4]): row[4] for row in old_db.execute(query, [policy]).fetchall()}
        new_days = {tuple(row[:4]): row[4] for row in con.execute(query, [policy]).fetchall()}
        series_days = {}
        for key in sorted(old_days.keys() & new_days.keys()):
            series_days.setdefault(key[:3], []).append((old_days[key], new_days[key]))
        samples = []
        for (station, pollutant, unit), values in series_days.items():
            old, new = zip(*values)
            precision = 4 if unit == "ppm" else 2
            label = pollutant_names.get(pollutant, pollutant)
            samples.append(f"<tr><td>{html.escape(station_names[station])}</td><td>{html.escape(label)} ({html.escape(unit)})</td>"
                           f"<td>{len(values)}</td><td>{mean(old):.{precision}f}</td><td>{mean(new):.{precision}f}</td></tr>")
        air_table = (f"<p>Air averages use the same station, pollutant, unit and days of the month, with at least {policy} hours "
            "in both years. Each eligible day has equal weight.</p><table><thead><tr><th>Station</th><th>Pollutant (unit)</th>"
            f"<th>Comparable days</th><th>{previous_label} mean</th><th>{period} mean</th></tr></thead>"
            f"<tbody>{''.join(samples)}</tbody></table>")
    shutil.copy2(previous_dir / "run.json", output / "comparison_build.json")
    return (f"<h2>Same-month comparison</h2><p>Pickups changed from {previous_trips:,} in {previous_label} to {totals[0]:,} "
            f"in {period} ({delta:+.1f}%). Those are two month snapshots. The comparison describes the observed periods.</p>"
            f"{air_table}<p><a href=\"comparison_build.json\">{previous_label} run evidence</a></p>")

def image_tag(name, alt):
    encoded = base64.b64encode((output/name).read_bytes()).decode()
    return f'<img alt="{html.escape(alt)}" src="data:image/png;base64,{encoded}">'
v = run["validation"]
check_rows = []
for check in v["checks"]:
    result = "Passed"
    if "expected" in check:
        result = f"Gold and Silver both total {check['actual']} USD"
    elif "exception_rows" in check:
        result = f"{check['exception_rows']} exceptions"
    label = html.escape(check["name"].replace("_", " "))
    check_rows.append(f"<tr><td>{label}</td><td>{html.escape(result)}</td></tr>")
rows = "".join(check_rows)
links = "".join(f'<li><a href="tables/{f.name}">{f.stem.replace("_"," ")}</a></li>' for f in exported_files)
air_images = "".join(image_tag(name, alt) for name, alt in air_charts)
period_comparison = comparison_section(*comparison) if comparison else ""
charge = trace["total_charged_usd"]
charge_label = f"${charge:,.2f} charged" if charge is not None else "charge missing"
group = trace_payload["gold_group"]
document = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fabric project local verification report</title>
<style>body{{font:17px/1.6 system-ui,sans-serif;color:#172033;background:#f1f5f9;margin:0}}main{{max-width:1140px;margin:auto;padding:44px 30px;background:white}}h1{{font-size:38px;line-height:1.15;max-width:850px}}h2{{margin-top:38px}}p{{max-width:920px}}.eyebrow{{font-size:13px;letter-spacing:.1em;color:#2856a6;font-weight:700}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin:30px 0}}.metric strong{{font-size:30px;display:block}}.metric span{{font-size:14px;color:#475569}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:15px}}td,th{{border-bottom:1px solid #dbe3ee;padding:9px;text-align:left}}summary{{cursor:pointer;font-weight:700}}a{{color:#2856a6}}.note{{color:#475569}}@media(max-width:700px){{main{{padding:24px 16px}}h1{{font-size:29px}}.metrics{{grid-template-columns:1fr}}}}@media print{{body{{background:white}}main{{padding:0}}details{{display:block}}}}</style>
<main><p class="eyebrow">VERIFIED LOCAL BUILD · FABRIC DEPLOYMENT PENDING</p>
<h1>New York taxi activity, air quality and economics</h1>
<p>Local reporting for {run['reporting_start']} to {run['reporting_end']} using official TLC, OpenAQ, ECB and World Bank sources. The run evidence records each completed validation stage.</p>
<p><a href="../docs/walkthrough.md">Rebuild the tables on one week of real data</a></p>
<div class="metrics"><div class="metric"><strong>{totals[0]:,}</strong><span>pickups inside the reporting period</span></div><div class="metric"><strong>${totals[2]:,.2f}</strong><span>recorded total charges, including negative entries</span></div><div class="metric"><strong>{totals[4]:,}</strong><span>zero-distance trips retained</span></div></div>
<details><summary>Follow one trip through the tables</summary>
<table><thead><tr><th>Stage</th><th>Where to find the record</th><th>What the data says</th></tr></thead><tbody>
<tr><td>Bronze</td><td>Source file row {trace['file_row_number']:,}</td><td>{trace['trip_distance']:g} miles and {charge_label}</td></tr>
<tr><td>Silver</td><td>Same source row, with typed fields</td><td>Pickup on {trace['pickup_date']}, hour {trace['pickup_hour']}, flagged for zero distance</td></tr>
<tr><td>Gold</td><td>{trace['pickup_date']} and {html.escape(trace_zone)}</td><td>The row is one of {group['trip_count']:,} pickups in that day and zone.</td></tr>
</tbody></table>
<p>Removing every zero-distance row would omit ${zero_distance_charges:,.2f} in net recorded charges from this reporting window. <a href="trace_example.json">See the source row and the exact Gold totals</a>.</p></details>
<h2>1. Mobility</h2>{image_tag('mobility_overview.png','Trips by day, pickup zone and hour, plus average base fare')}
<p>Recorded charges are values submitted in the trip records. The totals include {negatives[0]:,} rows with negative base fares, which sum to ${negatives[1] or 0:,.2f}.</p>
<h2>2. Currency and annual context</h2>{image_tag('economic_context.png','Matched USD and EUR charges, effective rates and annual US GDP')}
<p>EUR = USD ÷ USD per EUR. Weekends use the latest preceding published rate, at most seven days old. There are {v['uncovered_fx_dates']} uncovered dates. USD and EUR use the same eligible charge records. GDP shows annual US economic output in current dollars.</p>
<h2>3. Air quality and cross-domain comparison</h2><p>{html.escape(air_message)}</p>{air_images}{correlation_table}
{period_comparison}
<h2>4. Reconciliation and recovery</h2><p>All {v['source_rows']:,} source records remain in Silver. {v['reporting_rows']:,} have pickup dates inside the reporting window. {v['outside_reporting_window_rows']:,} are outside it, and {v['missing_pickup_date_rows']:,} lack a usable pickup date. Excluded reporting records remain traceable in detailed data.</p>
<p>Same-input rerun: {html.escape(run.get('same_input_rerun','not requested'))}. The build publishes its latest-success pointer only after validation passes.</p>
<details><summary>Inspect validation checks</summary><table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></details>
<h2>5. Files for the defense</h2>
<p><a href="../docs/learn_project.md">Architecture notes</a> · <a href="../docs/requirements.md">Requirement checklist</a> · <a href="local_build.json">Run evidence</a> · <a href="quality_summary.csv">Quality flag counts</a></p>
<details><summary>Download reporting tables</summary><ul>{links}</ul></details>
<p class="note">Run {run['run_id']} · completed {run['completed_at_utc']}. Seasonal conclusions require more overlapping history. Aggregate EUR values are rounded to four decimal places per date and zone.</p>
<p class="note">Data sources include <a href="https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page">NYC TLC</a>, <a href="https://docs.openaq.org/aws/about">OpenAQ</a>, <a href="https://data.cityofnewyork.us/Transportation/NYC-Taxi-Zones/8meu-9t5y/data_preview">NYC Taxi Zone boundaries</a>, <a href="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html">ECB</a> and <a href="https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json">World Bank</a>. Retrieval metadata and SHA-256 checksums appear in the run evidence.</p></main></html>'''
(output/"project_report.html").write_text(document,encoding="utf-8")
con.close()
print(f"Rendered report and charts from verified run {run['run_id']}")
