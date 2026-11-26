import { copyFile, mkdir, readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const source = new URL("reports/dashboard.json", root);
const out = new URL("dist/", root);
const report = JSON.parse(await readFile(source, "utf8"));
if (report.version !== 1 || report.platform !== "Databricks Delta" || !report.snapshots.length) {
  throw new Error("A verified Databricks dashboard export is required");
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
}
await mkdir(new URL("data/", out), { recursive: true });
await Promise.all([
  ...["index.html", "styles.css", "dashboard.js"].map((name) => copyFile(new URL(name, import.meta.url), new URL(name, out))),
  copyFile(source, new URL("data/snapshots.json", out)),
]);
process.stdout.write(`Prepared ${report.snapshots.length} verified Databricks snapshots in dist/\n`);
