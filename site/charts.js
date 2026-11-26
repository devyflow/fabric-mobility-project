const colors = ["#086d69", "#ab4f30"];
const charts = new Map();
const resize = new ResizeObserver((entries) => {
  for (const { target } of entries) paint(charts.get(target));
});

function scaleFor(values, bars) {
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const margin = (maximum - minimum) * .08 || Math.max(Math.abs(maximum) * .04, .1);
  const low = bars ? Math.min(0, minimum) : minimum >= 0 ? Math.max(0, minimum - margin) : minimum - margin;
  const high = bars ? Math.max(0, maximum) + margin : maximum + margin;
  return [low, high];
}

function paint(state) {
  if (!state) return;
  const { canvas, labels, series, tick, bars, active, selectedIndex } = state;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width < 1 || height < 1) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 3);
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.font = "11px Consolas, monospace";
  ctx.fillStyle = "#506169";
  const observed = series.flatMap((line) => line.values.filter(Number.isFinite));
  if (!observed.length) {
    state.axis = null;
    state.tip.hidden = true;
    ctx.fillText("No observations for this selection", 10, 24);
    return;
  }
  const [low, high] = scaleFor(observed, bars);
  const left = Math.max(33, ...[tick(low), tick(high)].map((label) => ctx.measureText(label).width + 8));
  const right = width - 13;
  const top = 10;
  const bottom = height - 23;
  const span = right - left;
  const n = labels.length;
  const x = bars ? (i) => left + (i + .5) * span / n : (i) => left + i * span / Math.max(n - 1, 1);
  const y = (number) => bottom - (number - low) / (high - low) * (bottom - top);
  state.axis = { left, right, x };

  ctx.textAlign = "right";
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  for (let i = 0; i <= 4; i++) {
    const v = low + i * (high - low) / 4;
    ctx.fillStyle = "#52616a";
    ctx.fillText(tick(v), left - 6, y(v) + 3);
    ctx.strokeStyle = "#dce2dd";
    ctx.beginPath();
    ctx.moveTo(left, y(v));
    ctx.lineTo(right, y(v));
    ctx.stroke();
  }
  const steps = Math.min(n - 1, width < 440 ? 3 : 5);
  ctx.textAlign = "center";
  for (let i = 0; i <= steps; i++) {
    const index = steps === 0 ? 0 : Math.round(i / steps * (n - 1));
    const label = labels[index];
    const half = ctx.measureText(label).width / 2;
    ctx.fillText(label, Math.min(width - half, Math.max(half, x(index))), height - 4);
  }

  series.forEach((line, s) => {
    const color = line.color || colors[s % colors.length];
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineJoin = "round";
    if (bars) {
      const barWidth = span / n * .70;
      line.values.forEach((v, i) => {
        if (!Number.isFinite(v)) return;
        ctx.fillStyle = i === active || i === line.peakIndex ? "#af7523" : color;
        ctx.fillRect(x(i) - barWidth / 2, Math.min(y(0), y(v)), barWidth, Math.max(1, Math.abs(y(0) - y(v))));
      });
      return;
    }
    // A missing observation breaks the line and its fill.
    const segments = [];
    let segment = [];
    line.values.forEach((v, i) => {
      if (Number.isFinite(v)) segment.push([x(i), y(v)]);
      else if (segment.length) { segments.push(segment); segment = []; }
    });
    if (segment.length) segments.push(segment);
    for (const points of segments) {
      ctx.beginPath();
      ctx.moveTo(...points[0]);
      for (const point of points.slice(1)) ctx.lineTo(...point);
      if (s === 0 && points.length > 1) {
        ctx.save();
        ctx.lineTo(points.at(-1)[0], bottom);
        ctx.lineTo(points[0][0], bottom);
        ctx.closePath();
        const wash = ctx.createLinearGradient(0, top, 0, bottom);
        wash.addColorStop(0, "#16867b26");
        wash.addColorStop(1, "#16867b03");
        ctx.fillStyle = wash;
        ctx.fill();
        ctx.restore();
        ctx.beginPath();
        ctx.moveTo(...points[0]);
        for (const point of points.slice(1)) ctx.lineTo(...point);
      }
      ctx.lineWidth = s ? 2 : 2.4;
      ctx.setLineDash(s ? [5, 4] : []);
      ctx.stroke();
      ctx.setLineDash([]);
      for (const point of points) {
        ctx.beginPath();
        ctx.arc(...point, s ? 1.6 : 2.0, 0, 2 * Math.PI);
        ctx.fill();
      }
    }
  });

  const cursor = active ?? selectedIndex;
  if (Number.isInteger(cursor) && cursor >= 0 && cursor < n) {
    ctx.strokeStyle = "#52616a";
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(x(cursor), top);
    ctx.lineTo(x(cursor), bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    series.forEach((line, index) => {
      const v = line.values[cursor];
      if (!Number.isFinite(v) || bars) return;
      ctx.fillStyle = line.color || colors[index % colors.length];
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x(cursor), y(v), 4.3, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
    });
  }

  state.tip.hidden = active == null;
  if (active != null) {
    state.tip.textContent = state.detail(active);
    const tipWidth = state.tip.offsetWidth;
    const desired = x(active) + 10 + tipWidth > width ? x(active) - tipWidth - 10 : x(active) + 10;
    state.tip.style.left = Math.max(1, Math.min(width - tipWidth - 1, desired)) + "px";
  }
}

function inspect(state, index) {
  const last = state.labels.length - 1;
  state.active = index == null || last < 0 ? null : Math.max(0, Math.min(last, index));
  paint(state);
}

function pointerIndex(state, event) {
  if (!state.axis) return null;
  const localX = event.clientX - state.canvas.getBoundingClientRect().left;
  const { left, right } = state.axis;
  if (localX < left - 4 || localX > right + 4) return null;
  const fraction = (localX - left) / (right - left);
  return state.bars ? Math.floor(fraction * state.labels.length) : Math.round(fraction * (state.labels.length - 1));
}

function bind(canvas, state) {
  canvas.addEventListener("pointermove", (event) => inspect(state, pointerIndex(state, event)));
  canvas.addEventListener("pointerleave", () => inspect(state, null));
  canvas.addEventListener("click", (event) => {
    const index = pointerIndex(state, event);
    if (index == null) return;
    inspect(state, index);
    state.onSelect?.(state.active);
  });
  canvas.addEventListener("focus", () => inspect(state, state.active ?? state.selectedIndex ?? 0));
  canvas.addEventListener("blur", () => inspect(state, null));
  canvas.addEventListener("keydown", (event) => {
    const index = state.active ?? 0;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      inspect(state, index + (event.key === "ArrowRight" ? 1 : -1));
    } else if (event.key === "Enter" || event.key === " ") {
      if (state.onSelect && state.axis) { event.preventDefault(); state.onSelect(index); }
    } else if (event.key === "Escape") inspect(state, null);
  });
  resize.observe(canvas);
}

export function chart(id, { labels, series, tick, detail, bars = false, onSelect, selectedIndex = null }) {
  const canvas = document.getElementById(id);
  let state = charts.get(canvas);
  if (!state) {
    const tip = canvas.parentElement.querySelector("output");
    tip.id = id + "-readout";
    tip.setAttribute("aria-live", "off");
    canvas.setAttribute("aria-describedby", tip.id);
    canvas.addEventListener("focus", () => tip.setAttribute("aria-live", "polite"));
    canvas.addEventListener("blur", () => tip.setAttribute("aria-live", "off"));
    state = { canvas, tip };
    charts.set(canvas, state);
    bind(canvas, state);
  }
  Object.assign(state, { labels, series, tick, detail, bars, onSelect, selectedIndex, active: null });
  paint(state);
}
