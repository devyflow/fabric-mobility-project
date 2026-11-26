const byId = (id) => document.getElementById(id);
const write = (id, value) => { byId(id).textContent = value; };
const whole = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const money = (currency, digits = 2) => new Intl.NumberFormat("en-US", {
  style: "currency", currency, maximumFractionDigits: digits, minimumFractionDigits: digits,
});
const dollars = money("USD");
const euros = money("EUR");
const value = (number) => number == null ? null : Number(number);
const perTrip = (total, count) => count > 0 && total != null ? Number(total) / count : null;
const formatted = (number, formatter) => number == null ? "Unavailable" : formatter.format(number);
const dateLabel = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const monthLabel = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
const monthText = (month) => monthLabel.format(new Date(month + "-01T00:00:00Z"));
const dateText = (date) => dateLabel.format(new Date(date + "T00:00:00Z"));
const hourText = (hour) => String(hour).padStart(2, "0") + ":00";
const pollutantText = { pm25: "PM2.5", no2: "NO₂", o3: "Ozone" };
const seriesColor = ["#097363", "#a54b29"];
const chartData = new Map();
let selected;
let snapshots;

function options(id, choices) {
  const select = byId(id);
  const prior = select.value;
  select.replaceChildren(...choices.map(([key, label]) => new Option(label, key)));
  if (choices.some(([key]) => String(key) === prior)) select.value = prior;
  select.disabled = choices.length === 0;
}

function draw(canvas, { labels, series, tick, bars, detail }) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width < 1 || height < 1) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.font = "12px Segoe UI, system-ui, sans-serif";
  context.fillStyle = "#4e635d";

  const values = series.flat().filter(Number.isFinite);
  if (!values.length) {
    context.fillText("No observations for this selection", 12, 28);
    return;
  }
  const extent = Math.max(...values) - Math.min(...values);
  const pad = extent > 0 ? .1 * extent : Math.max(Math.abs(values[0]) * .1, .1);
  const low = bars ? 0 : Math.max(0, Math.min(...values) - pad);
  const high = Math.max(low + pad, Math.max(...values) + pad);
  const left = Math.max(38, context.measureText(tick(high)).width + 13);
  const right = width - 13;
  const top = 12;
  const bottom = height - 28;
  const plotWidth = right - left;
  const x = (index) => bars
    ? left + (index + .5) * plotWidth / labels.length
    : left + index * plotWidth / Math.max(labels.length - 1, 1);
  const y = (number) => bottom - (number - low) * (bottom - top) / (high - low);

  context.textAlign = "right";
  for (let i = 0; i <= 4; i += 1) {
    const number = low + i * (high - low) / 4;
    context.fillText(tick(number), left - 7, y(number) + 4);
    context.strokeStyle = "#d9e2d8";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(left, y(number));
    context.lineTo(right, y(number));
    context.stroke();
  }

  context.textAlign = "center";
  const intervals = width < 490 ? 3 : 6;
  const labelsToDraw = new Set(Array.from({ length: intervals + 1 }, (_, index) =>
    Math.round(index * (labels.length - 1) / intervals)));
  for (const index of labelsToDraw) {
    const label = labels[index];
    const half = context.measureText(label).width / 2;
    context.fillText(label, Math.min(width - half, Math.max(half, x(index))), height - 7);
  }

  series.forEach((line, seriesIndex) => {
    const color = seriesColor[seriesIndex];
    if (bars) {
      context.fillStyle = color;
      const barWidth = plotWidth / labels.length * .7;
      line.forEach((number, index) => {
        if (Number.isFinite(number)) context.fillRect(x(index) - barWidth / 2, y(number), barWidth, bottom - y(number));
      });
      return;
    }
    context.strokeStyle = color;
    context.fillStyle = color;
    context.lineWidth = 2;
    context.lineJoin = "round";
    let started = false;
    context.beginPath();
    line.forEach((number, index) => {
      if (!Number.isFinite(number)) {
        started = false;
        return;
      }
      if (started) context.lineTo(x(index), y(number));
      else context.moveTo(x(index), y(number));
      started = true;
    });
    context.stroke();
    line.forEach((number, index) => {
      if (!Number.isFinite(number)) return;
      context.beginPath();
      context.arc(x(index), y(number), 2.3, 0, 2 * Math.PI);
      context.fill();
    });
  });
  canvas.onpointermove = (event) => {
    const offset = event.clientX - canvas.getBoundingClientRect().left - left;
    const position = bars ? Math.floor(offset / plotWidth * labels.length)
      : Math.round(offset / plotWidth * (labels.length - 1));
    if (position < 0 || position >= labels.length) return;
    canvas.title = detail?.[position] ?? labels[position];
  };
}

const resize = new ResizeObserver((entries) => {
  entries.forEach(({ target }) => draw(target, chartData.get(target)));
});

function chart(id, labels, series, tick, { bars = false, detail } = {}) {
  const canvas = byId(id);
  chartData.set(canvas, { labels, series, tick, bars, detail });
  resize.observe(canvas);
  draw(canvas, chartData.get(canvas));
}

function zoneBars(zones) {
  const rows = zones.slice(0, 8).map((zone) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = zone.zone_name;
    name.title = zone.borough;
    const track = document.createElement("span");
    track.className = "track";
    track.setAttribute("aria-hidden", "true");
    const bar = document.createElement("span");
    bar.style.width = `${100 * zone.trips / zones[0].trips}%`;
    track.append(bar);
    const count = document.createElement("strong");
    count.textContent = whole.format(zone.trips);
    item.append(name, track, count);
    return item;
  });
  byId("zone-bars").replaceChildren(...rows);
}

function mean(numbers) {
  const available = numbers.filter(Number.isFinite);
  return available.length ? available.reduce((total, number) => total + number, 0) / available.length : null;
}

function indexed(numbers) {
  const baseline = mean(numbers);
  return numbers.map((number) => number == null || !baseline ? null : number * 100 / baseline);
}

function drawPairs() {
  const pollutant = byId("pollutant").value;
  const zone = Number(byId("paired-zone").value);
  const comparison = selected.correlations.find((row) => row.pollutant === pollutant && row.zone_id === zone);
  const matching = (row) => comparison && row.zone_id === zone && row.pollutant === comparison.pollutant
    && row.unit === comparison.unit && row.source === comparison.source;
  const daily = new Map(selected.pairs.filter(matching).map((row) => [row.report_date, row]));
  const hourly = new Map(selected.paired_hour_profile.filter(matching).map((row) => [row.pickup_hour, row]));
  const dates = selected.days.map((row) => row.report_date);
  const hours = Array.from({ length: 24 }, (_, hour) => hour);
  const coefficient = comparison?.r == null ? "Pearson r unavailable" : `Pearson r ${comparison.r.toFixed(2)}`;
  write("correlation", comparison
    ? `${comparison.zone_name} · ${comparison.matched_days} matched days · ${coefficient}`
    : "No taxi and monitor overlaps for this pollutant");
  chart("paired-chart", dates.map(dateText), [
    indexed(dates.map((date) => daily.get(date)?.trip_count ?? null)),
    indexed(dates.map((date) => daily.get(date)?.concentration ?? null)),
  ], (number) => number.toFixed(0), { detail: dates.map((date) => {
    const row = daily.get(date);
    return row ? `${dateText(date)} · ${whole.format(row.trip_count)} trips · ${row.concentration.toFixed(2)} ${row.unit}`
      : `${dateText(date)} · No matched day`;
  }) });
  write("paired-hours", comparison ? `${comparison.zone_name} · ${pollutantText[pollutant]} · New York local time`
    : "No matched hours");
  chart("paired-hour-chart", hours.map(hourText), [
    indexed(hours.map((hour) => hourly.get(hour)?.average_trips ?? null)),
    indexed(hours.map((hour) => hourly.get(hour)?.concentration ?? null)),
  ], (number) => number.toFixed(0), { detail: hours.map((hour) => {
    const row = hourly.get(hour);
    return row ? `${hourText(hour)} · ${row.matched_days} days · ${Math.round(row.average_trips)} mean trips · ${row.concentration.toFixed(2)} ${row.unit}`
      : `${hourText(hour)} · No matched hours`;
  }) });
}

function drawStation() {
  const pollutant = byId("pollutant").value;
  const location = byId("station").value;
  const rows = selected.station_days.filter((row) => row.pollutant === pollutant && row.station_id === location);
  const station = rows[0];
  const dates = selected.days.map((row) => row.report_date);
  const observed = new Map(rows.map((row) => [row.report_date, row]));
  write("air-coverage", station ? `${station.zone_name} · ${station.source} · ${station.unit} · ${rows.length} days with readings`
    : "The selected period has no readings for this station");
  write("air-note", `Points use the hours available at that station. The taxi comparison uses station-days with at least ${selected.min_air_hours} valid hours.`);
  chart("air-chart", dates.map(dateText), [dates.map((date) => observed.get(date)?.concentration ?? null)],
    (number) => String(Number(number.toPrecision(3))), { detail: dates.map((date) => {
      const row = observed.get(date);
      return row ? `${dateText(date)} · ${row.concentration.toFixed(3)} ${row.unit} · ${row.observed_hours} hours`
        : `${dateText(date)} · No reading`;
    }) });
}

function changePollutant() {
  const pollutant = byId("pollutant").value;
  const stations = selected.station_days.filter((row) => row.pollutant === pollutant);
  options("station", [...new Map(stations.map((row) => [row.station_id, row.station_name]))]);
  const overlap = selected.correlations.filter((row) => row.pollutant === pollutant);
  options("paired-zone", [...new Map(overlap.map((row) => [row.zone_id, row.zone_name]))]);
  const strongest = overlap.filter((row) => row.matched_days >= 10 && Number.isFinite(row.r))
    .sort((a, b) => Math.abs(b.r) - Math.abs(a.r))[0];
  write("strongest-zone", strongest
    ? `Largest absolute correlation among zones with 10 or more matched days was ${strongest.zone_name} (r ${strongest.r.toFixed(2)}, ${strongest.matched_days} days).`
    : "No zone had both sufficient matched days and variation to rank its correlation.");
  drawStation();
  drawPairs();
}

function metricComparison() {
  const body = byId("comparison");
  const oneDecimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  const eligible = snapshots.map((snapshot) => snapshot.station_days.filter(
    (row) => row.observed_hours >= snapshot.min_air_hours,
  ));
  const stationSeries = (row) => [row.station_id, row.pollutant, row.unit, row.source].join("|");
  const shared = eligible.map((rows) => new Set(rows.map(stationSeries)))
    .reduce((a, b) => new Set([...a].filter((key) => b.has(key))));
  function airMean(snapshot, pollutant, unit) {
    return mean(snapshot.station_days.filter((row) => row.pollutant === pollutant && row.unit === unit
      && row.observed_hours >= snapshot.min_air_hours && shared.has(stationSeries(row))).map((row) => row.concentration));
  }
  body.replaceChildren(...snapshots.map((snapshot) => {
    const row = document.createElement("tr");
    const estGDP = value(snapshot.gdp[0]?.gdp_current_usd);
    const fields = [
      monthText(snapshot.month), whole.format(snapshot.total.trips),
      formatted(perTrip(snapshot.total.matched_usd, snapshot.total.fx_trip_count), dollars),
      formatted(airMean(snapshot, "pm25", "µg/m³"), oneDecimal),
      formatted(airMean(snapshot, "no2", "ppb"), oneDecimal),
      estGDP == null ? "Unavailable" : `$${compact.format(estGDP)}`,
    ];
    fields.forEach((field, index) => {
      const cell = document.createElement(index === 0 ? "th" : "td");
      if (index === 0) cell.scope = "row";
      cell.textContent = field;
      row.append(cell);
    });
    return row;
  }));
}

function changePeriod() {
  selected = snapshots.find((snapshot) => snapshot.month === byId("period").value);
  const { total, quality, days, hourly, zones } = selected;
  const earlier = snapshots.find((snapshot) => Number(snapshot.month.slice(0, 4)) === Number(selected.month.slice(0, 4)) - 1
    && snapshot.month.slice(4) === selected.month.slice(4));
  const delta = earlier ? 100 * (total.trips / earlier.total.trips - 1) : null;
  write("total-trips", whole.format(total.trips));
  write("trip-comparison", delta == null ? monthText(selected.month)
    : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}% vs ${monthText(earlier.month)}`);
  write("average-fare", formatted(perTrip(total.base_fare_usd, total.fare_count), dollars));
  write("total-charges", "$" + compact.format(value(total.charged_usd)));
  write("zero-distance", whole.format(total.zero_distance_trips));
  const busiestDay = days.reduce((best, row) => row.trips > best.trips ? row : best);
  const busiestHour = hourly.reduce((best, row) => row.trips > best.trips ? row : best);
  write("busiest-day", `Peak on ${dateText(busiestDay.report_date)} with ${whole.format(busiestDay.trips)} trips`);
  write("busiest-hour", `Peak at ${hourText(busiestHour.pickup_hour)} New York time with ${whole.format(busiestHour.trips)} trips`);
  const dates = days.map((row) => dateText(row.report_date));
  chart("trips-chart", dates, [days.map((row) => row.trips)], (number) => compact.format(number));
  chart("fare-chart", dates, [days.map((row) => perTrip(row.base_fare_usd, row.fare_count))], (number) => dollars.format(number));
  chart("hour-chart", hourly.map((row) => hourText(row.pickup_hour)), [hourly.map((row) => row.trips)],
    (number) => compact.format(number), { bars: true });
  zoneBars(zones);
  options("pollutant", ["pm25", "no2", "o3"]
    .filter((key) => selected.station_days.some((row) => row.pollutant === key)).map((key) => [key, pollutantText[key]]));
  changePollutant();
  write("avg-usd", formatted(perTrip(total.matched_usd, total.fx_trip_count), dollars));
  write("avg-eur", formatted(perTrip(total.matched_eur, total.fx_trip_count), euros));
  write("fx-coverage", `${whole.format(total.fx_trip_count)} trips had both a recorded charge and an applicable rate.`);
  write("converted-totals", total.fx_trip_count > 0
    ? `Those trips totaled ${dollars.format(total.matched_usd)} in USD and ${euros.format(total.matched_eur)} in EUR.`
    : "No charges qualified for conversion in this period.");
  const rates = days.map((row) => value(row.usd_per_eur));
  const knownRates = rates.filter(Number.isFinite);
  const lowRate = Math.min(...knownRates);
  const highRate = Math.max(...knownRates);
  write("rate-range", knownRates.length
    ? `${lowRate.toFixed(4)} to ${highRate.toFixed(4)} USD/EUR during the period`
    : "No eligible daily rates");
  write("rate-example", knownRates.length && lowRate < highRate
    ? `A $30 charge converts to ${euros.format(30 / lowRate)} at the lowest rate and ${euros.format(30 / highRate)} at the highest rate.`
    : "");
  chart("fx-chart", dates, [rates], (number) => number.toFixed(3));
  write("verification", `${whole.format(quality.source_rows)} source trips and ${whole.format(quality.silver_rows)} Silver rows reconciled. ${whole.format(quality.outside_reporting_window_rows)} trips fell outside the reporting month and stayed in Silver.`);
}

async function start() {
  try {
    const response = await fetch("/data/snapshots.json");
    if (!response.ok) throw new Error(`Snapshot request returned ${response.status}`);
    const data = await response.json();
    snapshots = data.snapshots.slice().sort((a, b) => b.month.localeCompare(a.month));
    options("period", snapshots.map((snapshot) => [snapshot.month, monthText(snapshot.month)]));
    byId("period").addEventListener("change", changePeriod);
    byId("pollutant").addEventListener("change", changePollutant);
    byId("station").addEventListener("change", drawStation);
    byId("paired-zone").addEventListener("change", drawPairs);
    byId("dashboard").hidden = false;
    changePeriod();
    metricComparison();
    byId("status").hidden = true;
  } catch (error) {
    console.error(error);
    write("status", "The snapshot data could not be loaded. Reload the page to retry.");
  }
}

start();
