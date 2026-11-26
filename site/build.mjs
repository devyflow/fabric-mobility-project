import { copyFile, cp, mkdir, readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const source = new URL("reports/dashboard.json", root);
const atlasSource = new URL("reports/zone_atlas.json", root);
const out = new URL("dist/", root);
const [report, atlas] = await Promise.all([source, atlasSource].map(async (url) => JSON.parse(await readFile(url, "utf8"))));
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
await mkdir(new URL("data/", out), { recursive: true });
await Promise.all([
  ...["index.html", "styles.css", "dashboard.js", "charts.js", "atlas.js", "favicon.png"].map((name) => copyFile(new URL(name, import.meta.url), new URL(name, out))),
  cp(new URL("fonts/", import.meta.url), new URL("fonts/", out), { recursive: true }),
  copyFile(source, new URL("data/snapshots.json", out)),
  copyFile(atlasSource, new URL("data/zone-atlas.json", out)),
]);
process.stdout.write(`Prepared ${report.snapshots.length} reconciled snapshots and the NYC zone atlas in dist/\n`);
