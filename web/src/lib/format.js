const UK = { timeZone: "Europe/London" };

/** Whole pounds: 1475000 -> "£14,750". */
export const money = (pence) => (pence == null ? "–" : "£" + Math.round(pence / 100).toLocaleString("en-GB"));

/** Pounds and pence: 32013 -> "£320.13". Finance figures are never rounded. */
export const money2 = (pence) =>
  pence == null
    ? "–"
    : "£" + (pence / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const miles = (value) => value.toLocaleString("en-GB");

export const timeOf = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

export const dateTimeOf = (iso) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** Which heading a chat sits under in the list. */
export function groupOf(iso) {
  const day = new Date(new Date(iso).toDateString());
  const today = new Date(new Date().toDateString());
  const days = Math.round((today - day) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return days < 7 ? "This week" : "Earlier";
}

/** When a car stops being available: UK date and time, how long is left, and how urgent that is. */
export function endsInfo(endsAt, now = Date.now()) {
  if (!endsAt) return { state: "open", date: "No end date", left: "Buy now: can sell at any time" };
  const end = new Date(endsAt);
  const part = (options) => end.toLocaleDateString("en-GB", { ...UK, ...options });
  const thisYear = part({ year: "numeric" }) === new Date(now).toLocaleDateString("en-GB", { ...UK, year: "numeric" });
  const clock = end.toLocaleTimeString("en-GB", { ...UK, hour: "numeric", minute: "2-digit", hour12: true }).replace(" ", "");
  const date =
    `${part({ weekday: "short" })} ${part({ day: "numeric", month: "short" })}` +
    (thisYear ? "" : ` ${part({ year: "numeric" })}`) +
    `, ${clock}`;
  const minutes = Math.floor((end - now) / 60000);
  if (minutes <= 0) return { state: "over", date, left: "Ended" };
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const left = days
    ? `${plural(days, "day")} ${plural(hours, "hr")} left`
    : hours
      ? `${plural(hours, "hr")} ${minutes % 60} min left`
      : `${minutes} min left`;
  return { state: minutes < 1440 ? "soon" : "", date, left };
}
