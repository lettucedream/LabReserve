export const TIME_ZONE = "Europe/Rome";
export const ACTIVE_BOOKINGS = new Set(["PENDING", "CONFIRMED", "WAITLISTED", "CANCELLING"]);
export const STATUS = {
  PENDING: ["In elaborazione", "pending"], CONFIRMED: ["Confermata", "confirmed"],
  WAITLISTED: ["In lista d’attesa", "waiting"], CANCELLING: ["Annullamento in corso", "pending"],
  CANCELLED: ["Annullata", "muted"], REJECTED: ["Non confermata", "rejected"],
  WAITING: ["In attesa", "waiting"], OFFERING: ["Assegnazione in corso", "pending"],
  WITHDRAWING: ["Uscita in corso", "pending"], WITHDRAWN: ["Uscita completata", "muted"],
};
const dateParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});
function parts(value) {
  return Object.fromEntries(dateParts.formatToParts(new Date(value)).map(p => [p.type, p.value]));
}
export function romeDay(value = new Date()) {
  const p = parts(value);
  return `${p.year}-${p.month}-${p.day}`;
}
export function romeLocal(value) {
  const p = parts(value);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
export function romeToISO(input) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(input)) throw new Error("Inserisci una data e un orario validi.");
  const raw = Date.parse(input + "Z");
  if (!Number.isFinite(raw)) throw new Error("Data non valida.");
  const matches = [1, 2].map(offset => raw - offset * 3600000).filter(time => romeLocal(time) === input);
  if (!matches.length) throw new Error("Questo orario non esiste a Roma per il cambio dell’ora. Scegline un altro.");
  if (matches.length > 1) throw new Error("Questo orario è ambiguo per il cambio dell’ora. Scegli una fascia fuori dal cambio dell’ora.");
  return new Date(matches[0]).toISOString();
}
export function visibleSlots(slots, labId, day, now = Date.now()) {
  return slots.filter(slot => !slot.lab_removed && Date.parse(slot.starts_at) > now && (!labId || slot.lab_id === Number(labId)) && (!day || romeDay(slot.starts_at) === day))
    .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at) || a.lab_id - b.lab_id);
}
export function activeForSlot(bookings, slotId) {
  return bookings.find(booking => booking.slot_id === slotId && ACTIVE_BOOKINGS.has(booking.status));
}
export function canJoinQueue(slot) { return slot.waiting_list_active || slot.available_seats === 0; }
