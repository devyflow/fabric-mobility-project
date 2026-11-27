const id = (name) => document.getElementById(name);
const integer = new Intl.NumberFormat("en-US");
const shortDay = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const formatDay = (iso) => shortDay.format(new Date(iso + "T00:00:00Z"));
const sum = (values) => values.reduce((total, value) => total + value, 0);
const palette = ["#f5f1df", "#dee6c6", "#b7d0ac", "#7eb49a", "#40877c", "#17574f"];
const monthBins = [0, 1, 100, 1000, 10000, 50000];
const dayBins = [0, 1, 5, 50, 250, 1500];
const boroughLabels = [
  ["Manhattan", -73.979, 40.783], ["Bronx", -73.864, 40.859], ["Queens", -73.814, 40.737],
  ["Brooklyn", -73.960, 40.652], ["Staten Island", -74.140, 40.565],
];

function geometry(zone) {
  const path = new Path2D();
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  for (const ring of zone.rings) {
    path.moveTo(...ring[0]);
    for (const [x, y] of ring) {
      path.lineTo(x, y);
      box[0] = Math.min(box[0], x);
      box[1] = Math.min(box[1], y);
      box[2] = Math.max(box[2], x);
      box[3] = Math.max(box[3], y);
    }
    path.closePath();
  }
  return { ...zone, path, box };
}

function extent(zones) {
  return [
    Math.min(...zones.map((z) => z.box[0])), Math.min(...zones.map((z) => z.box[1])),
    Math.max(...zones.map((z) => z.box[2])), Math.max(...zones.map((z) => z.box[3])),
  ];
}

function markerPoint(zone, context) {
  if (zone.marker) return zone.marker;
  const [x0, y0, x1, y1] = zone.box;
  const centerX = (x0 + x1) / 2;
  const centerY = (y0 + y1) / 2;
  let best = zone.rings[0][0];
  let nearest = Infinity;
  for (let xi = 1; xi <= 9; xi++) {
    for (let yi = 1; yi <= 9; yi++) {
      const x = x0 + (x1 - x0) * xi / 10;
      const y = y0 + (y1 - y0) * yi / 10;
      const distance = Math.hypot(x - centerX, y - centerY);
      if (distance < nearest && context.isPointInPath(zone.path, x, y, "evenodd")) {
        best = [x, y];
        nearest = distance;
      }
    }
  }
  zone.marker = best;
  return best;
}

function colorFor(trips, bins) {
  let bucket = 0;
  for (let i = 1; i < bins.length; i++) if (trips >= bins[i]) bucket = i;
  return palette[bucket];
}

function fillSelect(select, choices, current) {
  select.replaceChildren(...choices.map(([key, text]) => new Option(text, String(key))));
  if (choices.some(([key]) => String(key) === String(current))) select.value = String(current);
}

export function createAtlas(data, onDateChange) {
  const canvas = id("zone-map");
  const context = canvas.getContext("2d");
  const hitContext = document.createElement("canvas").getContext("2d");
  const zones = data.zones.filter((zone) => zone.rings.length).map(geometry);
  const lookup = new Map(zones.map((zone) => [zone.id, zone]));
  const borough = id("borough");
  const day = id("atlas-day");
  const chooseZone = id("atlas-zone");
  const hoverCard = id("map-hover");
  const boroughs = [...new Set(zones.map((zone) => zone.borough))].sort();
  fillSelect(borough, [["", "All boroughs"], ...boroughs.map((name) => [name, name])], "");

  let snapshot;
  let month;
  let sorted = [];
  let activeId;
  let focused = false;
  let hoverId = null;
  let transform;
  let counts = new Map();
  let totalTrips = 0;
  let bins = monthBins;
  let frame = 0;

  function toGrid(lon, lat) {
    const grid = data.grid;
    return [(lon - grid.west) * Math.cos(grid.latitude * Math.PI / 180) * grid.units_per_degree,
      (grid.north - lat) * grid.units_per_degree];
  }
  function mapPoint(lon, lat) {
    const [x, y] = toGrid(lon, lat);
    return [transform.tx + x * transform.scale, transform.ty + y * transform.scale];
  }

  function paint() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!sorted.length || !width || !height) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 3);
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const bounds = focused ? lookup.get(activeId).box : extent(sorted);
    const pad = focused ? .47 * Math.max(75, bounds[2] - bounds[0], bounds[3] - bounds[1]) : 0;
    const x0 = bounds[0] - pad, y0 = bounds[1] - pad, x1 = bounds[2] + pad, y1 = bounds[3] + pad;
    const margin = width < 440 ? 14 : 29;
    const scale = Math.min((width - 2 * margin) / (x1 - x0), (height - 56) / (y1 - y0));
    const tx = (width - (x1 - x0) * scale) / 2 - x0 * scale;
    const ty = 26 + (height - 56 - (y1 - y0) * scale) / 2 - y0 * scale;
    transform = { tx, ty, scale };
    const water = context.createLinearGradient(0, 0, width, height);
    water.addColorStop(0, "#eef2e9");
    water.addColorStop(1, "#cddfdc");
    context.fillStyle = water;
    context.fillRect(0, 0, width, height);
    context.font = "9px Consolas, monospace";
    context.textAlign = "left";
    context.lineWidth = .65;
    const step = borough.value ? .05 : .1;
    for (let i = 0; i < 18; i++) {
      const lat = 40.4 + i * step;
      const [, y] = mapPoint(-74, lat);
      if (y < 40 || y > height - 46) continue;
      context.strokeStyle = "#88a49a66";
      context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
      if (width > 420) { context.fillStyle = "#557267"; context.fillText(lat.toFixed(2) + "°N", 8, y - 4); }
    }
    for (let i = 0; i < 22; i++) {
      const [x] = mapPoint(-74.5 + i * step, 40.7);
      if (x < 0 || x > width) continue;
      context.strokeStyle = "#8ca79e60";
      context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
    }

    context.save();
    context.translate(tx, ty);
    context.scale(scale, scale);
    context.lineJoin = "round";
    for (const zone of zones) {
      const inBorough = !borough.value || zone.borough === borough.value;
      context.fillStyle = inBorough ? colorFor(counts.get(zone.id), bins) : "#e2e6d9";
      context.fill(zone.path, "evenodd");
      context.lineWidth = (focused ? 1.05 : .68) / scale;
      context.strokeStyle = inBorough && counts.get(zone.id) >= bins[4] ? "#a4c3aa" : inBorough ? "#658578" : "#bbc9bd";
      context.stroke(zone.path);
    }
    for (const zoneId of new Set([activeId, hoverId])) {
      const zone = lookup.get(zoneId);
      if (!zone) continue;
      context.lineWidth = 3.4 / scale;
      context.strokeStyle = "#28473a";
      context.stroke(zone.path);
      context.lineWidth = 1.8 / scale;
      context.strokeStyle = zoneId === activeId ? "#ffcf53" : "#fffef2";
      context.stroke(zone.path);
    }
    context.restore();

    context.textAlign = "center";
    context.font = "600 " + (width < 420 ? 9 : 11) + "px 'DM Sans', sans-serif";
    context.lineJoin = "round";
    for (const [name, lon, lat] of boroughLabels) {
      if (borough.value && borough.value !== name) continue;
      const [x, y] = mapPoint(lon, lat);
      context.lineWidth = 3;
      context.strokeStyle = "#edf1e6ed";
      context.fillStyle = "#244b3f";
      context.strokeText(name.toUpperCase(), x, y);
      context.fillText(name.toUpperCase(), x, y);
    }
    if (!focused && !borough.value && width > 505) {
      const [x, y] = mapPoint(-74.069, 40.669);
      context.font = "italic 11px Georgia, serif";
      context.fillStyle = "#4d736e";
      context.fillText("Upper Bay", x, y);
      const [ox, oy] = mapPoint(-73.891, 40.529);
      context.fillText("Atlantic Ocean", ox, oy);
    }
    const active = lookup.get(activeId);
    if (active) {
      const [mx, my] = markerPoint(active, hitContext);
      const x = tx + mx * scale;
      const y = ty + my * scale;
      if (focused) {
        // Leave room for the selected pin and its callout. Only label visible zone interiors.
        const occupied = [[x - 23, y - 34, x + Math.min(155, width / 4), y + 12]];
        context.font = "500 11px 'DM Sans', sans-serif";
        context.textAlign = "center";
        context.lineWidth = 3;
        context.strokeStyle = "#f4f4e8ed";
        context.fillStyle = "#294f44";
        for (const zone of sorted) {
          const [left, top, right, bottom] = zone.box;
          if (zone === active || tx + right * scale < 0 || tx + left * scale > width
              || ty + bottom * scale < 0 || ty + top * scale > height) continue;
          const [cx, cy] = markerPoint(zone, hitContext);
          const px = tx + cx * scale, py = ty + cy * scale;
          const half = context.measureText(zone.name).width / 2 + 4;
          const area = [px - half, py - 11, px + half, py + 4];
          if (area[0] < 7 || area[1] < 42 || area[2] > width - 7 || area[3] > height - 62
              || occupied.some(([l, t, r, b]) => area[0] < r && area[2] > l && area[1] < b && area[3] > t)) continue;
          context.strokeText(zone.name, px, py);
          context.fillText(zone.name, px, py);
          occupied.push(area);
          if (occupied.length > 7) break;
        }
      }
      if (width > 505) {
        context.font = "600 11px 'DM Sans', sans-serif";
        const boxWidth = context.measureText(active.name).width + 18;
        const toRight = x + boxWidth + 29 < width;
        const boxX = toRight ? x + 22 : x - 22 - boxWidth;
        const boxY = Math.max(35, Math.min(height - 57, y - 25));
        if (boxX >= 4 && boxX + boxWidth < width - 4) {
          context.strokeStyle = "#214d40";
          context.lineWidth = 1;
          context.beginPath();
          context.moveTo(x, y);
          context.lineTo(toRight ? boxX : boxX + boxWidth, boxY + 10);
          context.stroke();
          context.fillStyle = "#193b32f8";
          context.fillRect(boxX, boxY, boxWidth, 20);
          context.strokeRect(boxX + .5, boxY + .5, boxWidth - 1, 19);
          context.fillStyle = "#ffebad";
          context.textAlign = "left";
          context.fillText(active.name, boxX + 9, boxY + 14);
        }
      }
      context.fillStyle = "#14242c";
      context.strokeStyle = "#fff1a8";
      context.lineWidth = 2;
      context.beginPath(); context.arc(x, y, 5.5, 0, 2 * Math.PI); context.fill(); context.stroke();
      context.fillStyle = "#ffd15b";
      context.beginPath(); context.arc(x, y, 2, 0, 2 * Math.PI); context.fill();
    }
    // The display projection has the same nominal scale on both axes at NYC's reference latitude.
    const pixelsPerMetre = scale * data.grid.units_per_degree / 111320;
    const length = [25, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
      .filter((metres) => metres * pixelsPerMetre < Math.min(85, width * .18)).at(-1);
    if (length) {
      const end = width - 16, start = end - length * pixelsPerMetre, base = height - 54;
      context.strokeStyle = context.fillStyle = "#294c40";
      context.lineWidth = 1.25;
      context.beginPath(); context.moveTo(start, base - 4); context.lineTo(start, base);
      context.lineTo(end, base); context.lineTo(end, base - 4); context.stroke();
      context.textAlign = "right"; context.font = "10px 'DM Sans', sans-serif";
      context.fillText("≈ " + (length >= 1000 ? length / 1000 + " km" : length + " m"), end, base - 6);
    }
  }

  function queuePaint() {
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; paint(); });
  }

  function selectZone(zoneId) {
    if (!lookup.has(zoneId) || !sorted.some((zone) => zone.id === zoneId)) return;
    activeId = zoneId;
    id("share-status").textContent = "";
    id("share-address").hidden = true;
    chooseZone.value = String(zoneId);
    id("focus-zone").setAttribute("aria-pressed", String(focused));
    id("focus-zone").textContent = focused ? "Show area" : "Zoom to zone";
    const pickups = counts.get(zoneId);
    id("zone-trips").textContent = integer.format(pickups) + " pickups";
    const share = totalTrips ? (100 * pickups / totalTrips).toFixed(2) + "% of all recorded trips" : "No trips in period";
    id("zone-share").textContent = share;
    id("zone-bars").querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.zone) === zoneId));
    });
    canvas.setAttribute("aria-label", "NYC pickup map. Selected " + lookup.get(zoneId).name + ", " + integer.format(pickups) + " pickups. Use the pickup zone selector to explore.");
    queuePaint();
  }

  function updateLegend() {
    const format = new Intl.NumberFormat("en-US", { notation: "compact" });
    id("map-legend").replaceChildren(...bins.map((minimum, i) => {
      const entry = document.createElement("span");
      const chip = document.createElement("i");
      chip.style.background = palette[i];
      const next = bins[i + 1];
      entry.title = next ? integer.format(minimum) + " to " + integer.format(next - 1) + " pickups" : integer.format(minimum) + " pickups or more";
      entry.append(chip, format.format(minimum) + (next ? "" : "+"));
      return entry;
    }));
  }

  function updateRanking() {
    const top = sorted.filter((zone) => counts.get(zone.id) > 0).slice(0, 8);
    id("rank-scope").textContent = borough.value || "Five boroughs";
    id("zone-bars").replaceChildren(...top.map((zone, i) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.zone = zone.id;
      button.title = "Inspect " + zone.name;
      const parts = [["rank-no", String(i + 1).padStart(2, "0")], ["rank-name", zone.name],
        ["rank-count", integer.format(counts.get(zone.id))]];
      for (const [className, text] of parts) {
        const span = document.createElement("span");
        span.className = className;
        span.textContent = text;
        button.append(span);
      }
      const track = document.createElement("span");
      track.className = "rank-track";
      track.setAttribute("aria-hidden", "true");
      const bar = document.createElement("i");
      bar.style.width = (100 * counts.get(zone.id) / counts.get(top[0].id)) + "%";
      track.append(bar);
      button.append(track);
      button.addEventListener("click", () => selectZone(zone.id));
      item.append(button);
      return item;
    }));
    const mappedTotal = sum(sorted.map((zone) => counts.get(zone.id)));
    id("map-coverage").textContent = borough.value
      ? integer.format(mappedTotal) + " pickups across " + sorted.length + " mapped zones in " + borough.value + "."
      : sorted.length + " mapped zone IDs. " + integer.format(totalTrips - mappedTotal) + " pickups have other location codes and remain in the overall total.";
  }

  function refresh(preferLeader = false) {
    const dateIndex = month.dates.indexOf(day.value);
    totalTrips = dateIndex < 0 ? snapshot.total.trips : snapshot.days.find((row) => row.report_date === day.value).trips;
    counts = new Map(zones.map((zone) => {
      const series = month.pickups[zone.id];
      return [zone.id, dateIndex < 0 ? sum(series) : series[dateIndex]];
    }));
    bins = dateIndex < 0 ? monthBins : dayBins;
    sorted = zones.filter((zone) => !borough.value || zone.borough === borough.value)
      .sort((a, b) => counts.get(b.id) - counts.get(a.id) || a.id - b.id);
    fillSelect(chooseZone, [...sorted].sort((a, b) => a.name.localeCompare(b.name) || a.id - b.id)
      .map((zone) => [zone.id, zone.name + " · " + zone.borough + " #" + zone.id]), activeId);
    const next = !preferLeader && sorted.some((zone) => zone.id === activeId) ? activeId : sorted[0]?.id;
    id("map-caption").textContent = (borough.value || "New York City") + " / " + (day.value ? formatDay(day.value) : "Full month");
    updateLegend();
    updateRanking();
    hoverId = null;
    hoverCard.hidden = true;
    selectZone(next);
  }

  function hit(event) {
    if (!transform) return null;
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left - transform.tx) / transform.scale;
    const y = (event.clientY - rect.top - transform.ty) / transform.scale;
    return sorted.find(({ box, path }) => x >= box[0] && y >= box[1] && x <= box[2] && y <= box[3]
      && hitContext.isPointInPath(path, x, y, "evenodd"));
  }
  canvas.addEventListener("pointermove", (event) => {
    const zone = hit(event);
    if (hoverId !== (zone?.id ?? null)) { hoverId = zone?.id ?? null; queuePaint(); }
    canvas.style.cursor = zone ? "pointer" : "default";
    hoverCard.hidden = !zone;
    if (!zone) return;
    hoverCard.textContent = zone.name + " · " + integer.format(counts.get(zone.id)) + " pickups";
    const rect = canvas.getBoundingClientRect();
    hoverCard.style.left = Math.max(4, Math.min(canvas.clientWidth - hoverCard.offsetWidth - 4, event.clientX - rect.left + 12)) + "px";
    hoverCard.style.top = Math.max(5, Math.min(canvas.clientHeight - hoverCard.offsetHeight - 5, event.clientY - rect.top - hoverCard.offsetHeight - 8)) + "px";
  });
  canvas.addEventListener("pointerleave", () => { hoverId = null; hoverCard.hidden = true; queuePaint(); });
  canvas.addEventListener("click", (event) => { const zone = hit(event); if (zone) selectZone(zone.id); });
  borough.addEventListener("change", () => { focused = false; refresh(true); });
  day.addEventListener("change", () => { refresh(); onDateChange(day.value); });
  chooseZone.addEventListener("change", () => selectZone(Number(chooseZone.value)));
  id("focus-zone").addEventListener("click", () => {
    focused = !focused;
    hoverId = null;
    hoverCard.hidden = true;
    selectZone(activeId);
  });
  id("copy-map").addEventListener("click", async () => {
    const url = new URL(window.location.pathname, window.location.origin);
    url.searchParams.set("month", snapshot.month);
    if (borough.value) url.searchParams.set("borough", borough.value);
    if (day.value) url.searchParams.set("day", day.value);
    url.searchParams.set("zone", String(activeId));
    if (focused) url.searchParams.set("focus", "1");
    url.hash = "atlas";
    try {
      await window.navigator.clipboard.writeText(url.href);
      id("share-status").textContent = "Link copied.";
    } catch {
      const address = id("share-address");
      address.value = url.href;
      address.hidden = false;
      address.focus();
      address.select();
      id("share-status").textContent = "Copy the selected address.";
    }
  });
  id("reset-map").addEventListener("click", () => {
    focused = false; day.value = ""; borough.value = ""; refresh(true); onDateChange("");
  });
  new ResizeObserver(queuePaint).observe(canvas);
  document.fonts?.ready.then(queuePaint);

  return {
    setMonth(next, view) {
      snapshot = next;
      month = data.months[next.month];
      focused = false;
      const requestedDay = view?.get("day") ?? "";
      fillSelect(day, [["", "Full month"], ...month.dates.map((d) => [d, formatDay(d)])], requestedDay);
      if (view) {
        const requestedBorough = view.get("borough");
        borough.value = boroughs.includes(requestedBorough) ? requestedBorough : "";
        activeId = Number(view.get("zone"));
        const requestedZone = lookup.get(activeId);
        focused = view.get("focus") === "1" && !!requestedZone && (!borough.value || requestedZone.borough === borough.value);
      }
      refresh(!view);
    },
    setDate(iso) {
      if (!month.dates.includes(iso)) return;
      day.value = iso;
      refresh();
      onDateChange(iso);
    },
    getDate() { return day.value; },
  };
}
