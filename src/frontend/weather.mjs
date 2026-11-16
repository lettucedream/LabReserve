import { romeDay, TIME_ZONE } from "./domain.mjs";

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const valueLabel = (value, unit, digits = 0) => typeof value === "number" && Number.isFinite(value)
  ? `${new Intl.NumberFormat("it-IT", { maximumFractionDigits: digits }).format(value)}${unit}` : "—";
const localTime = value => new Intl.DateTimeFormat("it-IT", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" }).format(new Date(value));
const dateLabel = day => new Intl.DateTimeFormat("it-IT", { timeZone: TIME_ZONE, weekday: "long", day: "numeric", month: "long" }).format(new Date(`${day}T12:00:00Z`));
const source = '<a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a> · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer">CC BY 4.0</a>';

export function describeWeather(code, isDay = true) {
  if (code === 0) return [isDay ? "Cielo sereno" : "Notte serena", isDay ? "sun" : "moon"];
  if (code === 1) return ["Prevalentemente sereno", isDay ? "sun-cloud" : "cloud"];
  if (code === 2) return ["Parzialmente nuvoloso", isDay ? "sun-cloud" : "cloud"];
  if (code === 3) return ["Cielo coperto", "cloud"];
  if ([45, 48].includes(code)) return ["Nebbia", "fog"];
  if ([51, 53, 55].includes(code)) return ["Pioviggine", "rain"];
  if ([56, 57, 66, 67].includes(code)) return ["Pioggia gelata", "rain"];
  if ([61, 63, 65].includes(code)) return [["Pioggia debole", "Pioggia moderata", "Pioggia intensa"][[61, 63, 65].indexOf(code)], "rain"];
  if ([71, 73, 75, 77, 85, 86].includes(code)) return ["Neve", "snow"];
  if ([80, 81, 82].includes(code)) return ["Rovesci di pioggia", "rain"];
  if ([95, 96, 99].includes(code)) return ["Temporali", "storm"];
  return ["Condizioni non disponibili", "cloud"];
}

function icon(kind) {
  const sun = '<circle cx="24" cy="23" r="9" class="weather-sun"/><path d="M24 6v4m0 26v4M7 23h4m26 0h4M12 11l3 3m18 18 3 3m0-24-3 3M15 32l-3 3"/>';
  const cloud = '<path class="weather-cloud" d="M17 42h27a10 10 0 0 0 0-20h-1a14 14 0 0 0-27-2 11 11 0 0 0 1 22Z"/>';
  const shapes = {
    sun: sun, moon: '<path class="weather-moon" d="M43 40A21 21 0 0 1 24 8a21 21 0 1 0 28 28 21 21 0 0 1-9 4Z"/>',
    "sun-cloud": sun + cloud, cloud,
    rain: cloud + '<path d="m22 49-3 6m14-6-3 6m14-6-3 6"/>',
    snow: cloud + '<path d="M23 49v8m-4-4h8m14-4v8m-4-4h8"/>',
    storm: cloud + '<path class="weather-sun" d="m32 45-7 10h7l-4 8 13-13h-9l4-5Z"/>',
    fog: cloud + '<path d="M13 49h37M18 56h27"/>',
  };
  return `<svg class="weather-icon" viewBox="0 0 64 66" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes[kind] ?? cloud}</svg>`;
}

export function weatherMarkup(data, { loading = false, receivedAt = Date.now(), now = Date.now() } = {}) {
  const selected = data?.selected_date || romeDay(now), today = selected === romeDay(now);
  const age = (data?.data_age_seconds ?? 0) + Math.max(0, (now - receivedAt) / 1000);
  const hasData = data?.forecast && ["fresh", "stale"].includes(data.status) && age < data.max_age_seconds;
  const stale = hasData && (data.status === "stale" || age >= data.cache_seconds);
  const heading = `<div class="weather-heading"><h2 id="weather-title">Meteo alla Cittadella</h2><p class="weather-location">${today ? "Oggi" : escape(dateLabel(selected))}</p></div>`;
  if (!hasData) {
    const message = loading ? "Caricamento del meteo…" : data?.status === "out_of_range"
      ? `Previsioni disponibili dal ${dateLabel(data.available_from)} al ${dateLabel(data.available_to)}.`
      : "Meteo al momento non disponibile.";
    return `${heading}<div class="weather-empty"><p>${escape(message)}</p>${!loading && data?.status !== "out_of_range" ? '<button type="button" class="text-button" data-weather-refresh>Riprova</button>' : ""}</div><div class="weather-footer"><span>${source}</span></div>`;
  }
  const current = today ? data.current : null, forecast = data.forecast;
  const [condition, kind] = describeWeather(current?.weather_code ?? forecast.weather_code, current?.is_day ?? true);
  const temperature = current ? valueLabel(current.temperature_c, "") : `${valueLabel(forecast.temperature_min_c, "")}–${valueLabel(forecast.temperature_max_c, "")}`;
  const range = `Min ${valueLabel(forecast.temperature_min_c, "°")} · Max ${valueLabel(forecast.temperature_max_c, "°")}`;
  const facts = [
    ["Prob. pioggia", valueLabel(forecast.precipitation_probability_percent, "%")],
    [current ? "Vento" : "Vento max", valueLabel(current ? current.wind_kmh : forecast.wind_max_kmh, " km/h")],
  ];
  const readingAt = current?.valid_at || data.fetched_at;
  const updated = readingAt ? `<time datetime="${escape(readingAt)}">${current ? "Ore" : "Agg."} ${localTime(readingAt)}</time>` : "";
  return `${heading}<div class="weather-body"><div class="weather-summary">${icon(kind)}<div><div class="weather-temperature${current ? "" : " weather-temperature-range"}"${current ? "" : ` aria-label="${escape(range)}"`}>${temperature}<span>°C</span></div><p class="weather-condition">${escape(condition)}</p>${current ? `<p class="weather-range">${range}</p>` : ""}</div></div><dl class="weather-facts">${facts.map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("")}</dl></div>${stale ? '<p class="weather-warning" role="status">Ultimi dati disponibili</p>' : ""}<div class="weather-footer">${updated}<span>${source}</span></div>`;
}

export function mountWeather(root) {
  let selectedDate = null, data = null, receivedAt = 0, due = 0, timer = null, controller = null, generation = 0, pending = null;
  const render = loading => {
    root.setAttribute("aria-busy", String(loading));
    root.innerHTML = weatherMarkup(data || { selected_date: selectedDate || romeDay() }, { loading, receivedAt });
  };
  function schedule(seconds) {
    clearTimeout(timer);
    due = Date.now() + Math.max(2, Math.min(seconds, 600)) * 1000;
    if (!document.hidden) timer = setTimeout(() => refresh(), due - Date.now());
  }
  async function refresh() {
    if (pending) return pending;
    const context = generation, day = selectedDate || romeDay();
    controller = new AbortController();
    const requestController = controller;
    const timeout = setTimeout(() => requestController.abort(), 8000);
    render(true);
    const request = (async () => {
      try {
        const response = await fetch(`/api/availability/weather?${new URLSearchParams({ date: day })}`, { signal: requestController.signal, headers: { Accept: "application/json" }, cache: "no-store" });
        const result = await response.json();
        if ((!response.ok && response.status !== 503) || result.selected_date !== day || !["fresh", "stale", "unavailable", "out_of_range"].includes(result.status)) throw new Error("Risposta meteo non valida");
        if (context !== generation) return;
        data = result; receivedAt = Date.now();
        schedule(result.retry_after_seconds || 60);
      } catch {
        if (context !== generation) return;
        if (data?.forecast && (data.data_age_seconds + (Date.now() - receivedAt) / 1000) < data.max_age_seconds) data = { ...data, status: "stale" };
        else data = { status: "unavailable", selected_date: day };
        schedule(60);
      } finally {
        clearTimeout(timeout);
        if (context === generation) { pending = null; render(false); }
      }
    })();
    pending = request;
    return request;
  }
  function selectDate(day) {
    day ||= romeDay();
    if (day === selectedDate) return;
    generation++; controller?.abort(); clearTimeout(timer); pending = null;
    selectedDate = day; data = null; receivedAt = 0;
    refresh();
  }
  root.addEventListener("click", event => { if (event.target.closest("[data-weather-refresh]")) refresh(); });
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden) {
      render(false);
      if (Date.now() >= due) refresh(); else timer = setTimeout(() => refresh(), due - Date.now());
    }
  });
  window.addEventListener("pagehide", () => { generation++; controller?.abort(); clearTimeout(timer); pending = null; });
  window.addEventListener("pageshow", event => { if (event.persisted) refresh(); });
  return { selectDate, refresh };
}
