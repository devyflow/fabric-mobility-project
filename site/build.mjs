import { copyFile, cp, mkdir, readFile, writeFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const source = new URL("reports/dashboard.json", root);
const atlasSource = new URL("reports/zone_atlas.json", root);
const traceSource = new URL("reports/trace_example.json", root);
const out = new URL("dist/", root);
const [report, atlas, trace] = await Promise.all([source, atlasSource, traceSource].map(async (url) => JSON.parse(await readFile(url, "utf8"))));
if (report.version !== 1 || report.platform !== "Databricks Delta" || !report.snapshots.length) {
  throw new Error("A verified Databricks dashboard export is required");
}
const zoneIds = new Set(atlas.zones.map((zone) => String(zone.id)));
if (atlas.version !== 1 || atlas.zones.length !== zoneIds.size || !atlas.zones.some((zone) => zone.rings.length)
    || Object.keys(atlas.months).length !== report.snapshots.length) {
  throw new Error("The map requires unique TLC zones and the same periods as the dashboard");
}
for (const snapshot of report.snapshots) {
  const dateKeys = new Set(snapshot.days.map((row) => row.report_date));
  const hours = new Set(snapshot.hourly.map((row) => row.pickup_hour));
  const counted = (rows) => rows.reduce((sum, row) => sum + row.trips, 0);
  if (!/^\d{4}-\d{2}$/.test(snapshot.month) || dateKeys.size !== snapshot.days.length
      || counted(snapshot.days) !== snapshot.total.trips || counted(snapshot.hourly) !== snapshot.total.trips
      || hours.size !== snapshot.hourly.length || !snapshot.zones.length || !snapshot.station_days.length) {
    throw new Error(`Dashboard totals or table grains do not reconcile for ${snapshot.month}`);
  }
  const month = atlas.months[snapshot.month];
  if (!month || month.dates.length !== snapshot.days.length
      || month.dates.some((date, index) => date !== snapshot.days[index].report_date)
      || Object.keys(month.pickups).length !== zoneIds.size) {
    throw new Error("Atlas dates or zone IDs differ from the reporting period " + snapshot.month);
  }
  const daily = Array(month.dates.length).fill(0);
  for (const [id, values] of Object.entries(month.pickups)) {
    if (!zoneIds.has(id) || values.length !== daily.length || values.some((v) => !Number.isSafeInteger(v) || v < 0)) {
      throw new Error("Invalid daily pickup series for zone " + id);
    }
    values.forEach((v, i) => { daily[i] += v; });
  }
  if (daily.some((trips, i) => trips !== snapshot.days[i].trips)
      || snapshot.zones.some((zone) => month.pickups[zone.zone_id].reduce((n, v) => n + v, 0) !== zone.trips)) {
    throw new Error("Atlas trips differ from the checked Databricks export for " + snapshot.month);
  }
}
// Keep the historical case readable when a later publication covers different dates.
const trip = trace.source_and_silver;
const gold = trace.gold_group;
const zone = atlas.zones.find((item) => item.id === trip.pickup_zone_id);
const period = trip.pickup_date.slice(0, 7);
const month = atlas.months[period];
const dateOffset = month?.dates.indexOf(trip.pickup_date) ?? -1;
if (gold.report_date !== trip.pickup_date || gold.pickup_zone_id !== trip.pickup_zone_id
    || trip.trip_distance !== 0 || !trip.quality_flags.includes("zero_distance")) {
  throw new Error("The source trip and the illustrated Gold group disagree");
}
const hasMapGroup = dateOffset >= 0 && zone?.rings.length > 0 && month.pickups[zone.id]?.[dateOffset] === gold.trip_count;
const currency = new Intl.NumberFormat("en-US", {style: "currency", currency: "USD"});
const params = hasMapGroup && new URLSearchParams({month: period, borough: zone.borough, day: trip.pickup_date, zone: String(zone.id)});
const values = {
  row: trip.file_row_number, zone: zone?.name ?? "TLC zone " + trip.pickup_zone_id, time: trip.tpep_pickup_datetime.split(" ")[1],
  date: new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric", year: "numeric", timeZone: "UTC"}).format(new Date(trip.pickup_date + "T00:00:00Z")),
  miles: trip.trip_distance, baseFare: currency.format(trip.fare_amount), charge: currency.format(trip.total_amount),
  shortCharge: currency.format(trip.total_amount).replace(/\.00$/, ""), pickups: gold.trip_count.toLocaleString("en-US"),
  mapLink: hasMapGroup ? "/?" + params.toString() + "#atlas" : "#atlas",
  mapAction: hasMapGroup ? "Find this trip’s zone on the map" : "Explore the current pickup map",
};
const template = await readFile(new URL("index.html", import.meta.url), "utf8");
const html = template.replace(/\{\{(\w+)\}\}/g, (_, key) => {
  if (!Object.hasOwn(values, key)) throw new Error("Unknown trip field " + key);
  return String(values[key]).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");
});
await mkdir(new URL("data/", out), { recursive: true });
await Promise.all([
  writeFile(new URL("index.html", out), html),
  ...["styles.css", "dashboard.js", "charts.js", "atlas.js", "favicon.png"].map((name) => copyFile(new URL(name, import.meta.url), new URL(name, out))),
  cp(new URL("fonts/", import.meta.url), new URL("fonts/", out), { recursive: true }),
  cp(new URL("media/", import.meta.url), new URL("media/", out), { recursive: true }),
  copyFile(source, new URL("data/snapshots.json", out)),
  copyFile(atlasSource, new URL("data/zone-atlas.json", out)),
]);
process.stdout.write(`Prepared ${report.snapshots.length} reconciled snapshots and the NYC zone atlas in dist/\n`);
