import { createAtlas } from "./atlas.js";
import { chart, sparkline } from "./charts.js";

const el = (name) => document.getElementById(name);
const write = (name, text) => { el(name).textContent = text; };
const number = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const money = (currency) => new Intl.NumberFormat("en-US", { style: "currency", currency });
const usd = money("USD");
const eur = money("EUR");
const shortDay = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const longMonth = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
const dateOf = (iso) => new Date(iso + "T00:00:00Z");
const dateText = (iso) => shortDay.format(dateOf(iso));
const monthText = (month) => longMonth.format(dateOf(month + "-01"));
const hourText = (hour) => String(hour).padStart(2, "0") + ":00";
const numeric = (value) => value == null ? null : Number(value);
const perTrip = (total, count) => count > 0 && total != null ? Number(total) / count : null;
const formatted = (value, formatter) => value == null ? "Unavailable" : formatter.format(value);
const pollutants = { pm25: "PM2.5", no2: "NO₂", o3: "Ozone" };
let snapshots;
let selected;
let peer;
let atlas;
let pairMode = "daily";

function choose(name, entries, preference = el(name).value) {
  const select = el(name);
  select.replaceChildren(...entries.map(([key, label]) => new Option(label, String(key))));
  if (entries.some(([key]) => String(key) === String(preference))) select.value = String(preference);
  select.disabled = !entries.length;
}
function average(values) {
  const known = values.filter(Number.isFinite);
  return known.length ? known.reduce((sum, value) => sum + value, 0) / known.length : null;
}
function indexed(values) {
  const mean = average(values);
  return values.map((value) => value == null || !mean ? null : 100 * value / mean);
}
function legend(name, labels) {
  el(name).replaceChildren(...labels.map((label, i) => {
    const entry = document.createElement("span");
    const line = document.createElement("i");
    if (i) line.className = "line-two";
    entry.append(line, label);
    return entry;
  }));
}

function drawDaily() {
  const isFare = el("daily-metric").value === "fare";
  const metric = (row) => !row ? null : isFare ? perTrip(row.base_fare_usd, row.fare_count) : row.trips;
  const unit = (value) => value == null ? "No observation" : isFare ? usd.format(value) : number.format(value) + " pickups";
  const compare = peer && el("compare-period").checked;
  // June 5 is compared with June 5 of the other year, independent of weekday.
  const peerByDay = new Map((peer?.days ?? []).map((row) => [row.report_date.slice(8), row]));
  const days = selected.days;
  const primary = days.map(metric);
  const other = days.map((row) => metric(peerByDay.get(row.report_date.slice(8))));
  const lines = [{ values: primary }];
  if (compare) lines.push({ values: other });
  legend("daily-legend", compare ? [monthText(selected.month), monthText(peer.month)] : [monthText(selected.month)]);
  const observed = days.filter((row) => Number.isFinite(metric(row)));
  const peak = observed.length ? observed.reduce((best, row) => metric(row) > metric(best) ? row : best) : null;
  write("busiest-day", peak ? "Peak on " + dateText(peak.report_date) + " with " + unit(metric(peak)) + (isFare ? " average base fare" : "") + "." : "No recorded values.");
  const selectedIndex = days.findIndex((row) => row.report_date === atlas.getDate());
  chart("daily-chart", {
    labels: days.map((row) => dateText(row.report_date)), series: lines, tick: (v) => isFare ? usd.format(v) : compact.format(v),
    selectedIndex: selectedIndex < 0 ? null : selectedIndex,
    detail: (i) => dateText(days[i].report_date) + " · " + selected.month.slice(0, 4) + " " + unit(primary[i])
      + (compare ? "\n" + peer.month.slice(0, 4) + " " + unit(other[i]) : ""),
    onSelect: (i) => atlas.setDate(days[i].report_date),
  });
  const feedback = el("day-feedback");
  feedback.hidden = selectedIndex < 0;
  if (selectedIndex >= 0) feedback.textContent = "View " + dateText(days[selectedIndex].report_date) + " on the map ↑";
}

function drawHours() {
  const hours = selected.hourly;
  const peak = hours.reduce((best, row) => row.trips > best.trips ? row : best);
  write("busiest-hour", hourText(peak.pickup_hour) + " was busiest, with " + number.format(peak.trips) + " pickups.");
  chart("hour-chart", { labels: hours.map((r) => hourText(r.pickup_hour)), bars: true,
    series: [{ values: hours.map((r) => r.trips), peakIndex: hours.indexOf(peak) }],
    tick: (v) => compact.format(v), detail: (i) => hourText(hours[i].pickup_hour) + " · " + number.format(hours[i].trips) + " pickups",
  });
}

function stationChart(syncZone = false) {
  const pollutant = el("pollutant").value;
  const records = selected.station_days.filter((row) => row.pollutant === pollutant && row.station_id === el("station").value);
  const station = records[0];
  const days = selected.days.map((row) => row.report_date);
  const byDate = new Map(records.map((row) => [row.report_date, row]));
  write("air-coverage", station ? station.zone_name + " · " + station.source + " · " + station.unit + " · " + records.length + " observed days"
    : "No monitored readings for this selection.");
  write("air-note", "The daily mean uses the hours observed. A station-day needs " + selected.min_air_hours + " valid hours for a daily taxi comparison.");
  chart("air-chart", { labels: days.map(dateText), series: [{ values: days.map((d) => byDate.get(d)?.concentration ?? null) }],
    tick: (v) => String(Number(v.toPrecision(3))),
    detail: (i) => {
      const row = byDate.get(days[i]);
      return dateText(days[i]) + (row ? " · " + row.concentration.toFixed(3) + " " + row.unit + " · " + row.observed_hours + " hours" : " · No reading");
    },
  });
  if (syncZone && station && [...el("paired-zone").options].some((option) => option.value === String(station.zone_id))) {
    el("paired-zone").value = String(station.zone_id);
  }
  drawPair();
}

function drawPair() {
  const pollutant = el("pollutant").value;
  const zone = Number(el("paired-zone").value);
  const comparison = selected.correlations.find((row) => row.pollutant === pollutant && row.zone_id === zone);
  const same = (row) => comparison && row.zone_id === zone && row.pollutant === pollutant
    && row.unit === comparison.unit && row.source === comparison.source;
  const daily = pairMode === "daily";
  el("pair-daily").setAttribute("aria-pressed", String(daily));
  el("pair-hourly").setAttribute("aria-pressed", String(!daily));
  const rows = (daily ? selected.pairs : selected.paired_hour_profile).filter(same);
  const keys = daily ? selected.days.map((row) => row.report_date) : Array.from({ length: 24 }, (_, i) => i);
  const observations = new Map(rows.map((row) => [daily ? row.report_date : row.pickup_hour, row]));
  const records = keys.map((key) => observations.get(key));
  const labels = keys.map(daily ? dateText : hourText);
  const trips = records.map((row) => (daily ? row?.trip_count : row?.average_trips) ?? null);
  const air = records.map((row) => row?.concentration ?? null);
  const coefficient = comparison?.r == null ? "Pearson r unavailable" : "Pearson r " + comparison.r.toFixed(2);
  write("correlation", comparison
    ? comparison.zone_name + (daily ? " · " + comparison.matched_days + " matched days · " + coefficient : " · " + rows.length + " local hours with paired observations")
    : "No matched taxi and monitor observations.");
  write("pair-note", daily
    ? "Each line’s average across the matched days equals 100. Inspect a point for the original trips and concentration."
    : "Each hour averages its matched dates. Each line’s mean across the plotted hours equals 100.");
  chart("paired-chart", { labels, series: [{ values: indexed(trips) }, { values: indexed(air) }], tick: (v) => v.toFixed(0),
    detail: (i) => {
      const row = records[i];
      if (!row) return labels[i] + " · No matched observation";
      return labels[i] + " · " + number.format(daily ? trips[i] : Number(trips[i].toFixed(1))) + (daily ? " pickups" : " mean pickups")
        + " · " + row.concentration.toFixed(3) + " " + row.unit + (daily ? "" : "\n" + row.matched_days + " matched dates");
    },
  });
}

function changePollutant() {
  const pollutant = el("pollutant").value;
  const stations = selected.station_days.filter((row) => row.pollutant === pollutant);
  choose("station", [...new Map(stations.map((row) => [row.station_id, row.station_name]))]);
  const overlap = selected.correlations.filter((row) => row.pollutant === pollutant);
  choose("paired-zone", [...new Map(overlap.map((row) => [row.zone_id, row.zone_name]))]);
  const strongest = overlap.filter((row) => row.matched_days >= 10 && Number.isFinite(row.r)).sort((a, b) => Math.abs(b.r) - Math.abs(a.r))[0];
  write("strongest-zone", strongest
    ? "Among zones with at least 10 matched days, " + strongest.zone_name + " had the largest absolute daily " + pollutants[pollutant]
      + " correlation (r = " + strongest.r.toFixed(2) + ", " + strongest.matched_days + " days). Weather and other emissions can influence these readings."
    : "This selection has insufficient paired coverage or variation to rank the daily correlations.");
  stationChart(true);
}

function compareYears() {
  const seriesKey = (row) => [row.station_id, row.pollutant, row.unit, row.source].join("|");
  const covered = snapshots.map((s) => new Set(s.station_days.filter((r) => r.observed_hours >= s.min_air_hours).map(seriesKey)));
  const common = covered.reduce((a, b) => new Set([...a].filter((key) => b.has(key))));
  function pollutantMean(s, pollutant, unit) {
    const values = s.station_days.filter((r) => r.pollutant === pollutant && r.unit === unit
      && r.observed_hours >= s.min_air_hours && common.has(seriesKey(r))).map((r) => r.concentration);
    const mean = average(values);
    return mean == null ? "Unavailable" : mean.toFixed(1);
  }
  el("comparison").replaceChildren(...snapshots.map((s) => {
    const tr = document.createElement("tr");
    tr.classList.toggle("current", selected.month === s.month);
    const gdp = numeric(s.gdp[0]?.gdp_current_usd);
    const values = [monthText(s.month), number.format(s.total.trips), formatted(perTrip(s.total.matched_usd, s.total.fx_trip_count), usd),
      pollutantMean(s, "pm25", "µg/m³"), pollutantMean(s, "no2", "ppb"), gdp == null ? "Unavailable" : "$" + compact.format(gdp)];
    values.forEach((v, i) => {
      const cell = document.createElement(i ? "td" : "th");
      if (!i) cell.scope = "row";
      cell.textContent = v;
      tr.append(cell);
    });
    return tr;
  }));
}

function convertFare() {
  const input = el("fx-amount");
  const amount = input.valueAsNumber;
  const day = selected.days.find((row) => row.report_date === el("fx-day").value);
  const rate = numeric(day?.usd_per_eur);
  const validAmount = Number.isFinite(amount) && Number(amount.toFixed(2)) === amount;
  const validRate = Number.isFinite(rate) && rate > 0;
  write("fx-result", validAmount && validRate ? eur.format(amount / rate) : "—");
  if (!validAmount) {
    write("fx-explanation", "Enter a dollar amount with up to two decimal places.");
  } else if (!validRate) {
    write("fx-explanation", "No eligible ECB rate is available for this date.");
  } else {
    write("fx-explanation", "€1 = $" + rate.toFixed(4) + ". ECB reference date " + dateText(day.source_rate_date)
      + (day.rate_age_days > 0 ? " (" + day.rate_age_days + (day.rate_age_days === 1 ? " day" : " days") + " earlier)." : "."));
  }
  const rates = selected.days.map((row) => numeric(row.usd_per_eur)).filter((value) => Number.isFinite(value) && value > 0);
  if (rates.length) {
    const lowest = Math.min(...rates);
    const highest = Math.max(...rates);
    const acrossMonth = [amount / highest, amount / lowest].sort((a, b) => a - b);
    write("rate-example", validAmount
      ? "Across the month, " + usd.format(amount) + " ranged from " + eur.format(acrossMonth[0]) + " to " + eur.format(acrossMonth[1]) + " at the observed rates."
      : "During the month one euro bought $" + lowest.toFixed(4) + " to $" + highest.toFixed(4) + ".");
  } else {
    write("rate-example", "No eligible rates for this month.");
  }
}

function drawEconomy() {
  const { total, days } = selected;
  write("avg-usd", formatted(perTrip(total.matched_usd, total.fx_trip_count), usd));
  write("avg-eur", formatted(perTrip(total.matched_eur, total.fx_trip_count), eur));
  write("fx-coverage", number.format(total.fx_trip_count) + " trips have both a recorded charge and an exchange rate.");
  write("converted-totals", total.fx_trip_count > 0 ? "Those trips totaled " + usd.format(total.matched_usd) + " in USD and " + eur.format(total.matched_eur) + " in EUR." : "No recorded charges qualified for conversion.");
  const previousDay = el("fx-day").value.slice(8);
  choose("fx-day", days.map((row) => [row.report_date, dateText(row.report_date)]), selected.month + "-" + previousDay);
  convertFare();
  const rates = days.map((row) => numeric(row.usd_per_eur));
  const selectedIndex = days.findIndex((row) => row.report_date === el("fx-day").value);
  chart("fx-chart", { labels: days.map((row) => dateText(row.report_date)), series: [{ values: rates }], tick: (v) => v.toFixed(3),
    selectedIndex, detail: (i) => dateText(days[i].report_date) + (rates[i] == null ? " · No rate" : " · $" + rates[i].toFixed(4) + " per euro"),
    onSelect: (i) => { el("fx-day").value = days[i].report_date; drawEconomy(); },
  });
  compareYears();
}

function changeMonth(mapView) {
  selected = snapshots.find((s) => s.month === el("period").value);
  peer = snapshots.filter((s) => s !== selected && s.month.slice(5) === selected.month.slice(5))
    .sort((a, b) => Math.abs(Number(a.month.slice(0, 4)) - Number(selected.month.slice(0, 4)))
      - Math.abs(Number(b.month.slice(0, 4)) - Number(selected.month.slice(0, 4))))[0];
  const { total, quality } = selected;
  write("cover-period", monthText(selected.month));
  sparkline("spark-trips", selected.days.map((d) => d.trips), "Pickups", number, "#247362");
  sparkline("spark-fare", selected.days.map((d) => perTrip(d.base_fare_usd, d.fare_count)), "Average base fare", usd, "#956622");
  sparkline("spark-charges", selected.days.map((d) => numeric(d.charged_usd)), "Total charges", usd, "#356a74");
  sparkline("spark-zero", selected.days.map((d) => d.zero_distance_trips), "Zero-distance trips", number, "#92604a");
  write("total-trips", number.format(total.trips));
  write("average-fare", formatted(perTrip(total.base_fare_usd, total.fare_count), usd));
  write("total-charges", "$" + compact.format(Number(total.charged_usd)));
  write("zero-distance", number.format(total.zero_distance_trips));
  write("zero-share", total.trips ? (100 * total.zero_distance_trips / total.trips).toFixed(2) + "% of the month’s pickups" : "Recorded in Silver");
  const difference = peer?.total.trips ? 100 * (total.trips / peer.total.trips - 1) : null;
  el("trip-comparison").dataset.direction = difference < 0 ? "down" : "up";
  write("trip-comparison", difference == null ? monthText(selected.month) : (difference >= 0 ? "+" : "−") + Math.abs(difference).toFixed(1) + "% vs " + monthText(peer.month));
  el("compare-period").disabled = !peer;
  write("compare-label", peer ? "Compare with " + monthText(peer.month) : "Single reporting period");
  atlas.setMonth(selected, mapView);
  drawDaily();
  drawHours();
  choose("pollutant", Object.entries(pollutants).filter(([key]) => selected.station_days.some((row) => row.pollutant === key)));
  changePollutant();
  drawEconomy();
  write("verification", number.format(quality.source_rows) + " original taxi rows reconciled to " + number.format(quality.silver_rows)
    + " Silver rows. " + number.format(quality.outside_reporting_window_rows) + " fall outside the reporting month and remain in Silver.");
}

function trackNavigation() {
  const links = [...document.querySelectorAll(".topbar nav a")];
  const sections = links.map((link) => document.querySelector(link.hash));
  let queued = false;
  function update() {
    queued = false;
    const top = document.querySelector(".topbar").getBoundingClientRect().bottom + 55;
    let active = 0;
    sections.forEach((section, i) => { if (section.getBoundingClientRect().top <= top) active = i; });
    if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) active = sections.length - 1;
    links.forEach((link, i) => {
      if (i === active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }
  window.addEventListener("scroll", () => {
    if (!queued) { queued = true; requestAnimationFrame(update); }
  }, { passive: true });
  update();
}

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error("Could not load " + path);
  return response.json();
}

async function start() {
  write("status", "Loading the reporting data…");
  try {
    const [report, geo] = await Promise.all([getJson("/data/snapshots.json"), getJson("/data/zone-atlas.json")]);
    snapshots = report.snapshots.slice().sort((a, b) => b.month.localeCompare(a.month));
    atlas = createAtlas(geo, drawDaily);
    const view = new URLSearchParams(window.location.search);
    choose("period", snapshots.map((s) => [s.month, monthText(s.month)]), view.get("month"));
    el("period").addEventListener("change", () => changeMonth());
    el("daily-metric").addEventListener("change", drawDaily);
    el("compare-period").addEventListener("change", drawDaily);
    el("pollutant").addEventListener("change", changePollutant);
    el("station").addEventListener("change", () => stationChart(true));
    el("paired-zone").addEventListener("change", drawPair);
    el("pair-daily").addEventListener("click", () => { pairMode = "daily"; drawPair(); });
    el("pair-hourly").addEventListener("click", () => { pairMode = "hourly"; drawPair(); });
    el("fx-day").addEventListener("change", drawEconomy);
    el("fx-amount").addEventListener("input", convertFare);
    el("dashboard").hidden = false;
    changeMonth(view);
    el("status").hidden = true;
    trackNavigation();
    const section = document.getElementById(window.location.hash.slice(1));
    if (section?.matches("section") && !window.scrollY) requestAnimationFrame(() => section.scrollIntoView({ behavior: "instant" }));
  } catch (error) {
    console.error(error);
    el("dashboard").hidden = true;
    el("status").hidden = false;
    write("status", "The reporting files could not load. ");
    const retry = document.createElement("a");
    retry.href = window.location.href;
    retry.textContent = "Reload the dashboard";
    retry.addEventListener("click", (event) => { event.preventDefault(); window.location.reload(); });
    el("status").append(retry, ". The trip record and sources are available below.");
  }
}

start();
