import { ACTIVE_BOOKINGS, STATUS, TIME_ZONE, activeForSlot, canJoinQueue, romeDay, romeLocal, romeToISO, visibleSlots } from "./domain.mjs";
import { mountWeather } from "./weather.mjs";
import { mountAuth } from "./auth.mjs";

const $ = selector => document.querySelector(selector);
const weather = mountWeather($("#campus-weather"));
const safeStorage = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {  } },
};
const storedIntents = safeStorage.get("labreserve.intents", {});
const state = {
  user: null,
  labs: [], slots: [], bookings: [], waiting: [], notifications: [], errors: {}, loaded: false,
  view: "availability", lab: "", day: "", initialDay: true, context: 0, controller: null,
  refreshPromise: null, timer: null, busy: new Set(), manageLab: "",
  intents: storedIntents && typeof storedIntents === "object" && !Array.isArray(storedIntents) ? storedIntents : {},
};
const auth = mountAuth(changeSession);
const names = { availability: "Disponibilità", bookings: "Le mie prenotazioni", waiting: "Lista d’attesa", notifications: "Notifiche" };
const titles = { availability: "Disponibilità dei laboratori", bookings: "Le mie prenotazioni", waiting: "Lista d’attesa", notifications: "Notifiche" };
const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const format = (value, options) => new Intl.DateTimeFormat("it-IT", { timeZone: TIME_ZONE, ...options }).format(new Date(value));
const dayLabel = value => format(value, { weekday: "long", day: "numeric", month: "long" });
const timeLabel = value => format(value, { hour: "2-digit", minute: "2-digit" });
const rangeLabel = slot => `${timeLabel(slot.starts_at)} – ${timeLabel(slot.ends_at)}${romeDay(slot.starts_at) !== romeDay(slot.ends_at) ? " · " + dayLabel(slot.ends_at) : ""}`;
const labFor = slot => state.labs.find(lab => lab.id === slot?.lab_id);
const slotFor = id => state.slots.find(slot => slot.id === id);
const slotName = id => labFor(slotFor(id))?.name ?? `Fascia #${id}`;
const slotWhen = id => { const slot = slotFor(id); return slot ? `${dayLabel(slot.starts_at)} · ${rangeLabel(slot)}` : "Dettagli della fascia non disponibili"; };
const badge = status => { const [text, style] = STATUS[status] ?? [status, "muted"]; return `<span class="badge ${style}"><span class="badge-dot" aria-hidden="true"></span>${escape(text)}</span>`; };
const empty = (title, text, link = false) => `<div class="empty-state"><strong>${escape(title)}</strong>${escape(text)}${link ? '<br><a href="#availability">Vai alle disponibilità</a>' : ""}</div>`;
const disabled = value => value ? " disabled" : "";
const intentId = slotId => JSON.stringify([state.user, slotId]);

function region(id, html) {
  const element = $(id);
  if (element.dataset.rendered === html) return;
  const focused = element.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
  element.innerHTML = html;
  element.dataset.rendered = html;
  if (focused) element.querySelector(`[data-focus="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
}
function toast(message, error = false) {
  clearTimeout(toast.timer);
  const element = $("#toast"); element.textContent = message; element.classList.toggle("error", error); element.hidden = false;
  toast.timer = setTimeout(() => { element.hidden = true; }, error ? 8000 : 5000);
}
class RequestError extends Error { constructor(message, status = 0) { super(message); this.status = status; } }
async function api(service, path, { method = "GET", body, key, signal } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = setTimeout(abort, 15000);
  try {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (key) headers["Idempotency-Key"] = key;
    if (auth.session?.csrf_token && !["GET", "HEAD"].includes(method)) headers["X-CSRF-Token"] = auth.session.csrf_token;
    const response = await fetch(`/api/${service}${path}`, { method, headers, credentials: "same-origin", signal: controller.signal, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
    if (response.status === 401) auth.expire();
    if (response.status === 204) return null;
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const message = response.status >= 500 ? "Servizio temporaneamente non disponibile. Riprova tra poco." : typeof data?.detail === "string" ? data.detail : "Controlla i dati inseriti e riprova.";
      throw new RequestError(message, response.status);
    }
    if (data === null) throw new RequestError("Risposta non valida. Aggiorna i dati e riprova.");
    return data;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof RequestError) throw error;
    throw new RequestError("Connessione non riuscita. Controlla che la demo sia avviata e riprova.");
  } finally { clearTimeout(timeout); signal?.removeEventListener("abort", abort); }
}

async function availability(signal) {
  const labs = await api("availability", "/labs?include_removed=true", { signal });
  const results = await Promise.all(labs.map(async lab => {
    const slots = await api("availability", `/labs/${lab.id}/slots?include_removed=true`, { signal });
    return slots.map(slot => ({ ...slot, lab_removed: Boolean(lab.deleted_at) }));
  }));
  return { labs, slots: results.flat() };
}
function refresh() {
  if (!state.user) return Promise.resolve();
  if (state.refreshPromise) return state.refreshPromise;
  clearTimeout(state.timer);
  const context = state.context, user = state.user;
  const controller = new AbortController(); state.controller = controller;
  const query = new URLSearchParams({ user_id: user, limit: "200" });
  const names = ["availability", "booking", "waiting-list", "notification"];
  const promise = (async () => {
    const results = await Promise.allSettled([
      availability(controller.signal), api("booking", `/bookings?${query}`, { signal: controller.signal }),
      api("waiting-list", `/waiting-list?${query}`, { signal: controller.signal }), api("notification", `/notifications?${query}`, { signal: controller.signal }),
    ]);
    if (context !== state.context || controller.signal.aborted) return;
    results.forEach((result, index) => {
      const name = names[index];
      if (result.status === "rejected") state.errors[name] = result.reason.message;
      else {
        delete state.errors[name];
        if (index === 0) Object.assign(state, result.value);
        else state[["", "bookings", "waiting", "notifications"][index]] = result.value;
      }
    });
    if (state.initialDay && !state.errors.availability) {
      state.day = visibleSlots(state.slots, "", "")[0] ? romeDay(visibleSlots(state.slots, "", "")[0].starts_at) : romeDay();
      $("#date-filter").value = state.day; state.initialDay = false;
    }
    state.loaded = true; render();
  })().finally(() => {
    if (state.refreshPromise === promise) {
      state.refreshPromise = null;
      state.timer = setTimeout(() => { if (!document.hidden) refresh(); else state.timer = setTimeout(refresh, 10000); }, 2500);
    }
  });
  state.refreshPromise = promise;
  return promise;
}
function refreshAfterWrite() {
  state.controller?.abort(); clearTimeout(state.timer); state.refreshPromise = null;
  return refresh();
}

function renderSelectors() {
  const labs = state.labs.filter(lab => !lab.deleted_at);
  const options = labs.map(lab => `<option value="${lab.id}">${escape(lab.name)} · ${lab.capacity} ${lab.capacity === 1 ? "posto" : "posti"}</option>`).join("");
  region("#lab-filter", '<option value="">Tutti i laboratori</option>' + options);
  if (!labs.some(lab => String(lab.id) === state.lab)) state.lab = "";
  $("#lab-filter").value = state.lab;
  const current = $("#slot-lab").value;
  region("#slot-lab", options || '<option value="">Crea prima un laboratorio</option>');
  const selected = state.manageLab || current;
  if (labs.some(lab => String(lab.id) === selected)) $("#slot-lab").value = selected;
  $("#slot-form button[type=submit]").disabled = !labs.length || state.busy.has("slot-form");
  state.manageLab = "";
}
function renderAdminLabs() {
  if (auth.session?.user.role !== "admin") { region("#admin-labs-list", ""); return; }
  const labs = state.labs.filter(lab => !lab.deleted_at);
  region("#admin-labs-list", labs.length ? labs.map(lab => `<article class="record-card"><div class="record-body"><h4>${escape(lab.name)}</h4><p class="record-meta">${lab.capacity} ${lab.capacity === 1 ? "posto" : "posti"} · ${state.slots.filter(slot => slot.lab_id === lab.id).length} fasce</p></div><div class="record-actions"><button class="delete-button" type="button" data-delete-lab="${lab.id}" data-focus="delete-lab-${lab.id}"${disabled(state.errors.availability || state.busy.has(`delete-lab:${lab.id}`))}>Rimuovi<span class="sr-only"> ${escape(lab.name)}</span></button></div></article>`).join("") : empty("Nessun laboratorio presente", "Aggiungi un laboratorio con il modulo qui sopra."));
}
function renderSlots() {
  $("#slots-list").setAttribute("aria-busy", String(!state.loaded));
  if (!state.loaded) { region("#slots-list", empty("Caricamento…", "Recupero delle disponibilità per l’utente selezionato.")); return; }
  const slots = visibleSlots(state.slots, state.lab, state.day);
  if (state.errors.availability) { region("#slots-list", empty("Disponibilità non aggiornate", "Il servizio non è raggiungibile. La pagina riproverà automaticamente.")); return; }
  if (!slots.length) { region("#slots-list", empty("Nessuna fascia disponibile", "Prova un altro giorno o seleziona “Tutte le date”." + (auth.session?.user.role === "admin" ? " Puoi aggiungere fasce da Amministrazione." : ""))); return; }
  let previousDay = "";
  region("#slots-list", slots.map(slot => {
    const lab = labFor(slot), active = activeForSlot(state.bookings, slot.id), full = canJoinQueue(slot);
    const isBusy = state.busy.has(`book:${state.user}:${slot.id}`), retry = state.intents[intentId(slot.id)];
    const day = romeDay(slot.starts_at), heading = day !== previousDay ? `<h3 class="date-heading">${escape(dayLabel(slot.starts_at))}</h3>` : "";
    previousDay = day;
    const status = active ? badge(active.status) : "";
    const action = active ? `<a class="secondary-button" href="#${active.status === "WAITLISTED" ? "waiting" : "bookings"}">Vedi richiesta</a>`
      : `<button class="${full ? "secondary-button" : "primary-button"}" type="button" data-book="${slot.id}" data-focus="book-${slot.id}"${disabled(isBusy || state.errors.booking)}>${isBusy ? "Invio in corso…" : retry ? "Riprova richiesta" : full ? "Entra in lista" : "Prenota"}</button>`;
    const seatText = slot.waiting_list_active ? "Precedenza alla lista d’attesa" : slot.available_seats === 0 ? "Tutti i posti sono occupati" : `<strong>${slot.available_seats}</strong> ${slot.available_seats === 1 ? "posto libero" : "posti liberi"} su ${lab?.capacity ?? "—"}`;
    return `${heading}<article class="slot-card"><div class="slot-card-top"><div><h3>${escape(lab?.name ?? "Laboratorio")}</h3><p class="slot-time">${escape(rangeLabel(slot))}</p></div>${status}</div><div class="slot-card-bottom"><span class="seat-label${full ? " full" : ""}">${seatText}</span>${action}</div></article>`;
  }).join(""));
}
function renderNext() {
  const next = state.bookings.filter(row => row.status === "CONFIRMED" && !slotFor(row.slot_id)?.lab_removed && Date.parse(slotFor(row.slot_id)?.starts_at) > Date.now()).sort((a, b) => Date.parse(slotFor(a.slot_id).starts_at) - Date.parse(slotFor(b.slot_id).starts_at))[0];
  region("#next-booking", state.errors.booking ? '<p class="next-empty">Prenotazioni al momento non disponibili.</p>' : next ? `<p class="next-booking-title">${escape(slotName(next.slot_id))}</p><p class="next-booking-time">${escape(slotWhen(next.slot_id))}</p><a class="aside-link" href="#bookings">Vedi prenotazione</a>` : '<p class="next-empty">Nessuna prenotazione in programma.</p>');
}
function reasonText(row) {
  if (row.reason === "LAB_REMOVED") return "Il laboratorio è stato rimosso dall’amministratore.";
  if (ACTIVE_BOOKINGS.has(row.status) && slotFor(row.slot_id)?.lab_removed) return "Laboratorio rimosso. L’annullamento della richiesta è in corso.";
  if (row.status !== "REJECTED") return "";
  return { SLOT_NOT_FOUND: "La fascia non è più disponibile.", SLOT_STARTED: "La fascia è già iniziata.", TIMEOUT: "Non è stato possibile completare la richiesta in tempo. Puoi riprovare." }[row.reason] ?? "La richiesta non è stata confermata. Consulta le disponibilità per riprovare.";
}
function renderBookings() {
  if (!state.loaded) { region("#bookings-list", empty("Caricamento…", "Recupero delle tue richieste.")); return; }
  if (state.errors.booking && !state.bookings.length) { region("#bookings-list", empty("Prenotazioni non raggiungibili", "La pagina riproverà automaticamente tra poco.")); return; }
  const rows = state.bookings.filter(row => $("#show-history").checked || ACTIVE_BOOKINGS.has(row.status));
  region("#bookings-list", rows.length ? rows.map(row => `<article class="record-card"><div class="record-body"><h3>${escape(slotName(row.slot_id))}</h3>${badge(row.status)}<p class="record-meta">${escape(slotWhen(row.slot_id))}</p>${reasonText(row) ? `<p class="record-meta">${escape(reasonText(row))}</p>` : ""}</div><div class="record-actions">${ACTIVE_BOOKINGS.has(row.status) ? `<button class="text-button" type="button" data-cancel="${row.id}" data-focus="cancel-${row.id}"${disabled(row.status === "CANCELLING" || state.busy.has(`cancel:${row.id}`) || state.errors.booking)}>Annulla richiesta</button>` : ""}</div></article>`).join("") : empty("Nessuna prenotazione da mostrare", "Le prenotazioni e le richieste in attesa compariranno qui.", true));
}
function renderWaiting() {
  if (!state.loaded) { region("#waiting-list", empty("Caricamento…", "Recupero della lista d’attesa.")); return; }
  if (state.errors["waiting-list"] && !state.waiting.length) { region("#waiting-list", empty("Lista d’attesa non raggiungibile", "La pagina riproverà automaticamente tra poco.")); return; }
  region("#waiting-list", state.waiting.length ? state.waiting.map(row => `<article class="record-card queue-card"><div class="queue-position"><small>Posizione</small>${row.position ?? "—"}</div><div class="record-body"><h3>${escape(slotName(row.slot_id))}</h3>${badge(row.status)}<p class="record-meta">${escape(slotWhen(row.slot_id))}</p></div><div class="record-actions"><button class="text-button" type="button" data-withdraw="${row.id}" data-focus="withdraw-${row.id}"${disabled(row.status === "WITHDRAWING" || state.busy.has(`withdraw:${row.id}`) || state.errors["waiting-list"])}>Esci dalla lista</button></div></article>`).join("") : empty("Nessuna richiesta in lista d’attesa", "Puoi entrare in lista dalla pagina Disponibilità quando una fascia è piena.", true));
}
function renderNotifications() {
  if (!state.loaded) { region("#notifications-list", empty("Caricamento…", "Recupero dei tuoi aggiornamenti.")); return; }
  if (state.errors.notification && !state.notifications.length) { region("#notifications-list", empty("Notifiche non raggiungibili", "La pagina riproverà automaticamente tra poco.")); return; }
  const rows = state.notifications.filter(row => !$("#unread-only").checked || !row.read_at);
  const title = row => row.message.includes("laboratorio rimosso") ? "Prenotazione annullata: laboratorio rimosso" : ({ "booking.confirmed": "Prenotazione confermata", "booking.waitlisted": "Ingresso in lista d’attesa", "booking.cancelled": "Prenotazione annullata", "booking.rejected": "Prenotazione non confermata" })[row.event_type] ?? row.message;
  region("#notifications-list", rows.length ? rows.map(row => {
    const busy = state.busy.has(`read:${row.id}`) || state.busy.has(`delete:${row.id}`) || state.errors.notification;
    return `<article class="record-card notification-card${row.read_at ? "" : " unread"}"><div class="record-body"><h3>${escape(title(row))}</h3><p>${escape(slotName(row.slot_id))} · ${escape(slotWhen(row.slot_id))}</p><p>${escape(format(row.occurred_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))}</p></div><div class="record-actions"><button class="secondary-button" type="button" data-read="${row.id}" data-focus="read-${row.id}"${disabled(busy)}>${row.read_at ? "Segna da leggere" : "Segna come letta"}</button><button class="delete-button" type="button" data-delete-notification="${row.id}" data-focus="delete-${row.id}"${disabled(busy)}>Elimina</button></div></article>`;
  }).join("") : empty($("#unread-only").checked ? "Nessuna notifica da leggere" : "Nessuna notifica", "Qui trovi gli aggiornamenti sulle tue richieste."));
}
function render() {
  if (!state.user) return;
  weather.selectDate(state.day);
  renderSelectors(); renderAdminLabs(); renderSlots(); renderNext(); renderBookings(); renderWaiting(); renderNotifications();
  $("#bookings-count").textContent = state.bookings.filter(row => ACTIVE_BOOKINGS.has(row.status)).length || "";
  $("#waiting-count").textContent = state.waiting.length || "";
  const unread = state.notifications.filter(row => !row.read_at).length;
  $("#notification-count").textContent = unread ? `${unread}${state.notifications.length === 200 ? "+" : ""}` : "";
  const missing = Object.keys(state.errors);
  $("#service-alert").hidden = !missing.length;
  $("#service-alert").textContent = missing.length ? `Alcuni dati non sono aggiornati (${missing.map(key => ({ availability: "disponibilità", booking: "prenotazioni", "waiting-list": "lista d’attesa", notification: "notifiche" })[key]).join(", ")}). I dati già visibili possono essere precedenti. La pagina riproverà automaticamente.` : "";
  $("#sync-status").textContent = missing.length ? "Connessione parziale" : state.loaded ? "Aggiornato" : "Caricamento…";
  $("#sync-status").className = "sync-status " + (missing.length ? "offline" : state.loaded ? "live" : "");
}
function showView({ focus = false } = {}) {
  const view = location.hash.slice(1);
  state.view = Object.hasOwn(names, view) ? view : "availability";
  for (const [key, name] of Object.entries(names)) {
    $("#view-" + key).hidden = key !== state.view;
    const link = $(`[data-view="${key}"]`);
    if (key === state.view) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  $("#page-title").textContent = titles[state.view];
  document.title = state.user ? `${names[state.view]} · LabReserve` : "Accedi · LabReserve";
  if (focus) $("#main").focus({ preventScroll: true });
}
function userLabel() {
  const user = auth.session?.user;
  $("#user-label").textContent = user?.username || "";
  $("#user-avatar").textContent = [...(user?.username || "")][0]?.toLocaleUpperCase("it-IT") ?? "U";
  $("#user-role").textContent = user?.role === "admin" ? "Amministratore" : "Utente";
}
function changeSession(session) {
  state.controller?.abort(); state.context++; clearTimeout(state.timer); state.refreshPromise = null;
  state.user = session?.user.user_id || null; state.bookings = []; state.waiting = []; state.notifications = []; state.busy.clear();
  if (!session) {
    state.day = ""; state.initialDay = true;
    for (const id of ["#bookings-list", "#waiting-list", "#notifications-list", "#next-booking"]) region(id, "");
    for (const id of ["#bookings-count", "#waiting-count", "#notification-count"]) $(id).textContent = "";
    $("#service-alert").hidden = true;
  }
  state.errors = {}; state.loaded = false; $("#show-history").checked = false; $("#unread-only").checked = false;
  $("#toast").hidden = true; userLabel(); showView(); render(); if (session) refresh();
}

async function bookSlot(slotId) {
  const user = state.user, context = state.context, busyId = `book:${user}:${slotId}`, intent = intentId(slotId);
  if (state.busy.has(busyId) || activeForSlot(state.bookings, slotId)) return;
  let key = state.intents[intent];
  if (typeof key !== "string" || key.length > 128 || !key.trim()) key = crypto.randomUUID();
  state.intents[intent] = key; safeStorage.set("labreserve.intents", state.intents);
  state.busy.add(busyId); renderSlots();
  try {
    const row = await api("booking", "/bookings", { method: "POST", key, body: { user_id: user, slot_id: slotId } });
    delete state.intents[intent]; safeStorage.set("labreserve.intents", state.intents);
    if (context === state.context) {
      state.bookings = [row, ...state.bookings.filter(value => value.id !== row.id)];
      toast("Richiesta inviata. Qui vedrai la conferma o la posizione in lista d’attesa."); render();
    }
  } catch (error) {
    if (error.status >= 400 && error.status < 500) { delete state.intents[intent]; safeStorage.set("labreserve.intents", state.intents); }
    if (context === state.context) toast(error.message, true);
  } finally { state.busy.delete(busyId); if (context === state.context) { renderSlots(); await refreshAfterWrite(); } }
}
let confirmation = null;
function confirmCancellation(id, queue) {
  const row = (queue ? state.waiting : state.bookings).find(value => value.id === id);
  if (!row) return;
  confirmation = { id, queue, context: state.context };
  $("#confirm-title").textContent = queue ? "Uscire dalla lista d’attesa?" : "Annullare la richiesta?";
  $("#confirm-description").textContent = `${slotName(row.slot_id)} · ${slotWhen(row.slot_id)}. ${queue ? "Perderai la tua posizione. Se vorrai rientrare, ripartirai dal fondo della lista." : "Il posto eventualmente assegnato sarà reso disponibile a chi aspetta."}`;
  $("#confirm-action").textContent = queue ? "Esci dalla lista" : "Annulla richiesta";
  $("#confirm-dialog").showModal();
}
async function cancelRequest() {
  const intent = confirmation; confirmation = null; $("#confirm-dialog").close();
  if (!intent || intent.context !== state.context) return;
  const { id, queue, context } = intent, busyId = `${queue ? "withdraw" : "cancel"}:${id}`;
  if (state.busy.has(busyId)) return;
  state.busy.add(busyId); render();
  try {
    const row = await api(queue ? "waiting-list" : "booking", `/${queue ? "waiting-list" : "bookings"}/${id}`, { method: "DELETE" });
    if (context === state.context) {
      const collection = queue ? "waiting" : "bookings";
      state[collection] = state[collection].map(value => value.id === id ? row : value);
      toast(queue ? "Uscita dalla lista richiesta. Lo stato si aggiornerà tra poco." : "Annullamento richiesto. Lo stato si aggiornerà tra poco.");
    }
  } catch (error) { if (context === state.context) toast(error.status === 409 && queue ? "La richiesta ha già un esito. Controlla le tue prenotazioni prima di annullarla." : error.message, true); }
  finally { state.busy.delete(busyId); if (context === state.context) { render(); await refreshAfterWrite(); } }
}
async function markRead(id) {
  const row = state.notifications.find(value => value.id === id), context = state.context, busyId = `read:${id}`;
  if (!row || state.busy.has(busyId) || state.busy.has(`delete:${id}`)) return;
  state.busy.add(busyId); renderNotifications();
  try {
    const result = await api("notification", `/notifications/${id}`, { method: "PATCH", body: { is_read: !row.read_at } });
    if (context === state.context) { state.notifications = state.notifications.map(value => value.id === id ? result : value); render(); }
  } catch (error) { if (context === state.context) toast(error.message, true); }
  finally { state.busy.delete(busyId); if (context === state.context) { renderNotifications(); await refreshAfterWrite(); } }
}
async function deleteNotification(id) {
  const context = state.context, busyId = `delete:${id}`;
  if (state.busy.has(busyId) || state.busy.has(`read:${id}`)) return;
  state.busy.add(busyId); renderNotifications();
  try {
    await api("notification", `/notifications/${id}`, { method: "DELETE" });
    if (context === state.context) { state.notifications = state.notifications.filter(row => row.id !== id); render(); toast("Notifica eliminata."); }
  } catch (error) { if (context === state.context) toast(error.message, true); }
  finally { state.busy.delete(busyId); if (context === state.context) { renderNotifications(); await refreshAfterWrite(); } }
}
async function submitForm(event, type) {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  state.busy.add(form.id);
  const result = $(`#${type}-result`); result.textContent = "Invio in corso…"; result.classList.remove("error"); button.disabled = true;
  try {
    const data = new FormData(form);
    if (type === "lab") {
      const name = String(data.get("name")).trim();
      if (!name) throw new Error("Inserisci un nome per il laboratorio.");
      const lab = await api("availability", "/labs", { method: "POST", body: { name, capacity: Number(data.get("capacity")) } });
      state.manageLab = String(lab.id); result.textContent = `“${lab.name}” creato. Ora aggiungi una fascia nel secondo modulo.`; form.reset();
    } else {
      const starts_at = romeToISO(String(data.get("start"))), ends_at = romeToISO(String(data.get("end")));
      if (Date.parse(starts_at) <= Date.now()) throw new Error("L’inizio deve essere nel futuro.");
      if (Date.parse(ends_at) <= Date.parse(starts_at)) throw new Error("La fine deve essere successiva all’inizio.");
      await api("availability", `/labs/${Number(data.get("lab"))}/slots`, { method: "POST", body: { starts_at, ends_at } });
      state.day = romeDay(starts_at); state.lab = String(data.get("lab")); $("#date-filter").value = state.day;
      result.textContent = "Fascia aggiunta. Chiudi questa finestra per vederla nelle disponibilità.";
    }
    await refreshAfterWrite();
  } catch (error) { result.classList.add("error"); result.textContent = error.message; }
  finally { state.busy.delete(form.id); button.disabled = false; renderSelectors(); }
}

let labRemoval = null;
function confirmLabRemoval(id) {
  const lab = state.labs.find(lab => lab.id === id && !lab.deleted_at);
  if (!lab || auth.session?.user.role !== "admin") return;
  labRemoval = { id, context: state.context };
  $("#lab-delete-description").textContent = `Stai per rimuovere “${lab.name}” (${lab.capacity} ${lab.capacity === 1 ? "posto" : "posti"}).`;
  $("#lab-delete-result").textContent = "";
  $("#lab-delete-dialog").showModal();
}
async function removeLab() {
  const intent = labRemoval, button = $("#lab-delete-action"), result = $("#lab-delete-result");
  if (!intent || intent.context !== state.context || button.disabled || auth.session?.user.role !== "admin") return;
  const busyId = `delete-lab:${intent.id}`;
  button.disabled = true; state.busy.add(busyId); result.textContent = "Rimozione in corso…"; result.classList.remove("error"); renderAdminLabs();
  try {
    await api("availability", `/labs/${intent.id}`, { method: "DELETE" });
    if (intent.context === state.context) {
      state.labs = state.labs.map(lab => lab.id === intent.id ? { ...lab, deleted_at: new Date().toISOString() } : lab);
      state.slots = state.slots.map(slot => slot.lab_id === intent.id ? { ...slot, lab_removed: true } : slot);
      labRemoval = null; $("#lab-delete-dialog").close(); render();
      toast("Laboratorio rimosso. L’annullamento delle prenotazioni e delle attese è in corso.");
      await refreshAfterWrite();
    }
  } catch (error) { if (intent.context === state.context) { result.textContent = error.message; result.classList.add("error"); } }
  finally { state.busy.delete(busyId); button.disabled = false; if (intent.context === state.context) renderAdminLabs(); }
}

$("#lab-filter").addEventListener("change", event => { state.lab = event.target.value; renderSlots(); });
$("#date-filter").addEventListener("change", event => { state.day = event.target.value; renderSlots(); weather.selectDate(state.day); });
$("#all-dates").addEventListener("click", () => { state.day = ""; $("#date-filter").value = ""; renderSlots(); weather.selectDate(""); });
$("#show-history").addEventListener("change", renderBookings); $("#unread-only").addEventListener("change", renderNotifications);
$("#refresh").addEventListener("click", async () => { const button = $("#refresh"); button.disabled = true; try { await Promise.allSettled([refresh(), weather.refresh()]); } finally { button.disabled = false; } });
$("#manage-open").addEventListener("click", () => {
  if (auth.session?.user.role !== "admin") return;
  const tomorrow = Date.now() + 86400000;
  const form = $("#slot-form"); if (!form.elements.start.value) { form.elements.start.value = romeLocal(tomorrow); form.elements.end.value = romeLocal(tomorrow + 3600000); }
  $("#manage-dialog").showModal();
  auth.loadUsers();
});
$("#lab-form").addEventListener("submit", event => submitForm(event, "lab"));
$("#slot-form").addEventListener("submit", event => submitForm(event, "slot"));
$("#lab-delete-action").addEventListener("click", removeLab);
$("#lab-delete-dialog").addEventListener("close", () => { labRemoval = null; });
$("#confirm-action").addEventListener("click", cancelRequest);
$(".skip-link").addEventListener("click", event => { event.preventDefault(); $("#main").focus(); });
document.addEventListener("click", event => {
  const target = event.target.closest("button"); if (!target || target.disabled) return;
  if (target.dataset.close) $("#" + target.dataset.close).close();
  else if (target.dataset.book) bookSlot(Number(target.dataset.book));
  else if (target.dataset.cancel) confirmCancellation(target.dataset.cancel, false);
  else if (target.dataset.withdraw) confirmCancellation(target.dataset.withdraw, true);
  else if (target.dataset.read) markRead(target.dataset.read);
  else if (target.dataset.deleteNotification) deleteNotification(target.dataset.deleteNotification);
  else if (target.dataset.deleteLab) confirmLabRemoval(Number(target.dataset.deleteLab));
});
window.addEventListener("hashchange", () => showView({ focus: true }));
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
showView(); auth.restore();
