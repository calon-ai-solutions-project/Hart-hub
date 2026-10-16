import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { sim } from "../api/client.js";
import { dateTimeOf, money, money2, timeOf } from "../lib/format.js";
import SideNav from "./SideNav.jsx";

const TABS = [
  ["bot", "Bot handling"],
  ["person", "Needs a person"],
  ["chosen", "Chosen a car"],
];
const TAB_OF_STEP = { needs_person: "person", handed_over: "chosen" }; // every other step is the bot's
const POLL_MS = 5000; // how often open data is refreshed
const ALERT_MS = 10000; // how often "a customer chose a car" is checked

/** Run `tick` now and then every `ms`, but only while the browser tab is visible; again as soon as it is shown.
 *  Ticks never overlap, so a slow answer is never asked for twice. */
function usePoll(tick, ms) {
  useEffect(() => {
    let stopped = false;
    let running = false;
    const run = async () => {
      if (stopped || running || document.hidden) return;
      running = true;
      try {
        await tick();
      } catch {
        /* the next tick tries again */
      } finally {
        running = false;
      }
    };
    run();
    const timer = setInterval(run, ms);
    document.addEventListener("visibilitychange", run);
    return () => {
      stopped = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, [tick, ms]);
}

const pretty = (phone) => phone.replace(/^\+44(\d{4})(\d{6})$/, "+44 $1 $2");
// Ofcom's drama range: 07700 900000 to 900999 never belongs to a real person
const testNumber = () => `+447700900${String(100 + Math.floor(Math.random() * 900))}`;

/** Message text with *bold* and clickable links, built without any HTML from the server. */
function Rich({ text }) {
  return text.split("\n").map((line, i) => (
    <span key={i} className="line">
      {line.split(/(https?:\/\/\S+|\*[^*]+\*)/g).map((part, j) => {
        if (/^https?:\/\//.test(part)) {
          return (
            <a key={j} href={part} target="_blank" rel="noopener noreferrer">
              {part}
            </a>
          );
        }
        if (/^\*[^*]+\*$/.test(part)) return <b key={j}>{part.slice(1, -1)}</b>;
        return part;
      })}
    </span>
  ));
}

// how a message the Hub sent got on with WhatsApp
const DELIVERY = {
  sent: ["✓", "Sent"],
  delivered: ["✓✓", "Delivered"],
  read: ["✓✓", "Read"],
  failed: ["!", "Not delivered"],
  skipped: ["–", "Not sent (not a test number)"],
};

/** The customer's side of the chat. In the simulator staff type as the customer; on real WhatsApp it is read only. */
function Phone({ phone, onActivity, readOnly, live }) {
  const [messages, setMessages] = useState([]);
  const [notes, setNotes] = useState([]); // what the Hub did with messages it does not store
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const chat = useRef(null);

  const load = useCallback(async () => {
    const data = await sim.phone(phone);
    setMessages(data.messages);
  }, [phone]);

  usePoll(load, POLL_MS);

  useEffect(() => {
    if (chat.current) chat.current.scrollTop = chat.current.scrollHeight;
  }, [messages.length, notes.length]);

  async function send(body) {
    body = body.trim();
    if (!body || busy) return;
    setBusy(true);
    setText("");
    try {
      const answer = await sim.inbound(phone, body);
      if (answer.ignored) {
        // personal: nothing is stored, so the phone shows it only until the page is reloaded
        setNotes((now) => [...now, { id: `${Date.now()}`, body, at: new Date().toISOString() }]);
      }
      await load();
      onActivity(answer.enquiry);
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    if (!window.confirm(`Clear everything stored for ${pretty(phone)}?`)) return;
    await sim.clear(phone);
    setNotes([]);
    await load();
    onActivity(null);
  }

  const empty = messages.length === 0 && notes.length === 0;
  return (
    <div className="phone">
      <div className="screen">
        <div className="wa-head">
          <span className="avatar">{phone.slice(-2)}</span>
          <div className="wa-who">
            <b>{pretty(phone)}</b>
            <small>{live ? "WhatsApp customer" : "Test customer"}</small>
          </div>
          {!readOnly && !live && !empty && (
            <button type="button" className="wa-clear" onClick={clear} title="Start this number again">
              Clear
            </button>
          )}
        </div>
        <div className="business-line">Hart Group · WhatsApp Business</div>
        <div className="wa-chat" ref={chat}>
          {messages.map((message) => (
            <div key={message.id} className={`wa-msg ${message.direction === "in" ? "in" : "out"}`}>
              {message.direction === "out" && (
                <span className="wa-from">{message.sender === "staff" ? message.staff_name : "Hart Group"}</span>
              )}
              {message.media_url && <img className="wa-photo" src={message.media_url} alt="" loading="lazy" />}
              <Rich text={message.body} />
              <span className="wa-time">
                {timeOf(message.created_at)}
                {message.direction === "out" && DELIVERY[message.delivery] && (
                  <span className={`wa-tick ${message.delivery}`} title={DELIVERY[message.delivery][1]}>
                    {" "}{DELIVERY[message.delivery][0]}
                  </span>
                )}
              </span>
            </div>
          ))}
          {notes.map((note) => (
            <div key={note.id}>
              <div className="wa-msg in">
                <Rich text={note.body} />
                <span className="wa-time">{timeOf(note.at)}</span>
              </div>
              <div className="wa-note stop">
                <b>AI: Personal message.</b> No reply, no form, not saved in the Hub. The owner answers it themselves.
              </div>
            </div>
          ))}
        </div>
        {live ? (
          <div className="wa-composer read-only">The Hub replies automatically. To write yourself, use WhatsApp on the business phone.</div>
        ) : readOnly ? (
          <div className="wa-composer read-only">Read only: your role can view conversations, not send.</div>
        ) : (
          <form className="wa-composer" onSubmit={(event) => { event.preventDefault(); send(text); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type as the customer…"
                   aria-label="Message from the customer" />
            <button disabled={busy || !text.trim()} aria-label="Send">➤</button>
          </form>
        )}
      </div>
    </div>
  );
}

function Seconds({ from, to }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (to) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [to]);
  if (!from) return null;
  const seconds = Math.round(((to ? new Date(to) : now) - new Date(from)) / 1000);
  return <>{Math.floor(seconds / 60)}m {String(seconds % 60).padStart(2, "0")}s</>;
}

/** "5 min ago", "2 h ago", "Yesterday", or the date. */
function ago(iso) {
  if (!iso) return "";
  const minutes = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h`;
  if (minutes < 48 * 60) return "Yesterday";
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

// the customer's journey, in order; a step is done once the enquiry has moved past it
const AFTER_DETAILS = [
  ["quoting", "Quoting"],
  ["awaiting_approval", "Approval"],
  ["options_sent", "Options sent"],
  ["handed_over", "Car chosen"],
];
const JOURNEY = {
  chat: [["chatting", "Chatting"], ["form_done", "Details"], ...AFTER_DETAILS],
  form: [["form_sent", "Form sent"], ["form_done", "Form filled"], ...AFTER_DETAILS],
};

/** When the car's deal ends, in UK time: the day, the time, and a warning colour when it is close. */
function Ends({ at }) {
  if (!at) return <span className="ends-open">Immediate</span>;
  const end = new Date(at);
  const hours = (end - Date.now()) / 3600000;
  const uk = { timeZone: "Europe/London" };
  return (
    <span className={hours <= 0 ? "ends-over" : hours < 24 ? "ends-soon" : ""}>
      <b>{end.toLocaleDateString("en-GB", { ...uk, day: "numeric", month: "short" })}</b>
      <small>{hours <= 0 ? "Ended" : end.toLocaleTimeString("en-GB", { ...uk, hour: "2-digit", minute: "2-digit" })}</small>
    </span>
  );
}

function Journey({ step, by }) {
  const steps = JOURNEY[by] || JOURNEY.chat;
  const at = steps.findIndex(([key]) => key === step);
  if (at < 0) return null;
  const finished = at === steps.length - 1; // the customer chose a car: every step is done
  return (
    <ol className="journey" aria-label="Where this customer is">
      {steps.map(([key, label], i) => {
        const done = i < at || finished;
        return (
          <li key={key} className={done ? `done${i === at ? " last" : ""}` : i === at ? "now" : ""}>
            <span className="dot">{done ? "✓" : i + 1}</span>
            <span className="label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** The queue: one row per customer, with their last message. */
function EnquiryList({ list, selected, onSelect, search, setSearch }) {
  const shown = useMemo(() => {
    const digits = search.replace(/\D/g, "");
    return list.enquiries.filter((e) => !digits || e.phone.replace(/\D/g, "").includes(digits));
  }, [list.enquiries, search]);
  return (
    <section className="wa-list" aria-label="Enquiries">
      <label className="wa-search">
        <span className="sr-only">Search by phone number</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by phone number" />
      </label>
      <div className="wa-rows">
        {shown.length === 0 && (
          <div className="wa-list-empty">
            <b>{search ? "No match" : "All clear"}</b>
            <span>{search ? "No enquiry has that number." : "Nothing in this queue right now."}</span>
          </div>
        )}
        {shown.map((e) => {
          const last = e.last_message || {};
          return (
            <button key={e.id} type="button" className={`wa-row${e.id === selected ? " on" : ""}`} onClick={() => onSelect(e)}>
              <span className="avatar">{e.phone.slice(-2)}</span>
              <span className="wa-row-main">
                <span className="wa-row-top">
                  <b>{pretty(e.phone)}</b>
                  <small>{ago(last.at || e.updated_at)}</small>
                </span>
                <span className="wa-row-preview">
                  {last.direction === "out" && <em>You: </em>}
                  {last.body || "No messages"}
                </span>
                <span className="wa-row-meta">
                  <span className={`status ${e.step}`}>{e.step_label}</span>
                  {e.assigned_to && <span className="owner">{e.assigned_to.split("@")[0]}</span>}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/** One enquiry: the journey, what the customer wants, the quoted cars and approval. Replies are sent from
 *  WhatsApp on the salesperson's phone, not from here. */
function EnquiryDetail({ detail, user, onChange }) {
  const [problem, setProblem] = useState("");
  const [working, setWorking] = useState(false);

  async function approve() {
    setWorking(true);
    setProblem("");
    try {
      onChange(await sim.approve(detail.id));
    } catch (error) {
      setProblem(error.message);
    } finally {
      setWorking(false);
    }
  }

  if (!detail) {
    return (
      <section className="wa-detail wa-detail-empty">
        <div className="empty-art" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M4 5h16v11H8l-4 4zM8 9h8M8 12h5" /></svg>
        </div>
        <h2>Select an enquiry</h2>
        <p>Pick a customer from the queue to see their request, quotes and progress.</p>
      </section>
    );
  }

  const request = detail.request;
  const answers = detail.answers || {};
  const said = (value) => ({ any: "Any", none: "None", Auto: "Automatic" })[value] || value;
  const wants = request ? [
    ["Car", [request.make, request.model].filter(Boolean).join(" ") || request.notes || "Any car"],
    ["Colour", request.colours.join(", ")],
    ["Gearbox", { auto: "Automatic", manual: "Manual" }[request.gearbox]],
    ["Monthly budget", request.monthly_budget_pence && money(request.monthly_budget_pence)],
    ["Deposit", request.deposit_pence != null && money(request.deposit_pence)],
    ["Needed by", request.needed_by],
    ["Part-exchange", request.part_exchange],
  ].filter(([, value]) => value) : Object.keys(answers).length > 0 && [ // still chatting: what they've said so far
    ["Car", said(answers.make_model)],
    ["Monthly budget", answers.monthly_budget],
    ["Deposit", answers.deposit],
    ["Gearbox", said(answers.gearbox)],
    ["Part-exchange", said(answers.part_exchange)],
    ["Colour", answers.colour],
    ["Needed by", answers.needed_by],
  ].filter(([, value]) => value);

  return (
    <section className="wa-detail">
      <header className="wa-detail-head">
        <span className="avatar big">{detail.phone.slice(-2)}</span>
        <div className="title">
          <h2>{pretty(detail.phone)}</h2>
          <div className="wa-chips">
            <span className="chip">{detail.intent_label}</span>
            <span className="chip subtle">
              {detail.intent_by === "ai" ? "AI" : "Rules"}
              {detail.intent_confidence != null && ` · ${Math.round(detail.intent_confidence * 100)}% sure`}
            </span>
            <span className="chip subtle">Started {dateTimeOf(detail.created_at)}</span>
            {detail.assigned_to && <span className="chip owner">Assigned to {detail.assigned_to}</span>}
          </div>
        </div>
        <span className={`status big ${detail.step}`}>{detail.step_label}</span>
      </header>

      <Journey step={detail.step} by={detail.collected_by} />
      {detail.loading && (
        <div className="loading-rows" aria-label="Loading">
          <div className="skeleton" />
          <div className="skeleton tall" />
        </div>
      )}

      {detail.needs_person_reason && (
        <div className="notice warn">
          <b>Needs a person.</b> {detail.needs_person_reason}
        </div>
      )}
      {detail.step === "handed_over" && detail.chosen_title && (
        <div className="notice good">
          <b>Customer chose option {detail.chosen_number}: {detail.chosen_title}.</b> Carry on the conversation in
          WhatsApp on your phone, from the same business number.
        </div>
      )}
      {!detail.loading && !detail.can_act && (
        <div className="notice">
          {user.role === "admin" ? "Read only: your role can view enquiries, not act on them."
                                 : `This enquiry is handled by ${detail.assigned_to}.`}
        </div>
      )}

      {wants && (
        <section className="wa-card">
          <h3>{request ? "Customer request" : "So far in the chat"}</h3>
          <dl className="facts">
            {wants.map(([name, value]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {detail.quoting_started_at && (
        <div className={`quoting${detail.step === "quoting" ? " live" : ""}`}>
          {detail.step === "quoting" ? <span className="spinner" /> : <span className="tick">✓</span>}
          <span>
            Codeweavers · {detail.quotes_tried} car{detail.quotes_tried === 1 ? "" : "s"} tried · {detail.options.length}{" "}
            quoted
          </span>
          <span className="time">
            <Seconds from={detail.quoting_started_at} to={detail.quoting_finished_at} />
          </span>
        </div>
      )}

      {detail.options.length > 0 && (
        <section className="wa-card flush">
          <h3>Cars and finance quotes</h3>
          <div className="options-table">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Car</th>
                  <th className="num">Price</th>
                  <th className="num">Monthly</th>
                  <th>Ends</th>
                  <th className="staffcol">Staff only</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {detail.options.map((o) => {
                  const q = o.customer.quote;
                  const chosen = detail.chosen_number === o.number;
                  return (
                    <tr key={o.number} className={chosen ? "chosen" : ""}>
                      <td className="n">{o.number}</td>
                      <td className="car">
                        <b>{o.customer.card.title}</b>
                        <small>
                          {[o.customer.card.year, o.customer.card.mileage != null && `${o.customer.card.mileage.toLocaleString("en-GB")} mi`]
                            .filter(Boolean).join(" · ")}
                          {o.staff.quote_note && <em> · {o.staff.quote_note}</em>}
                        </small>
                      </td>
                      <td className="num">{money(o.customer.card.price_pence)}</td>
                      <td className="num">
                        <b>{money2(q.monthly_pence)}</b>
                        <small>{money(q.deposit_pence)} deposit</small>
                      </td>
                      <td className="ends-cell"><Ends at={o.customer.card.ends_at} /></td>
                      <td className="staffcol staff-cell">
                        <b>{o.staff.platform}</b>
                        <small>Platform {money(o.staff.buy_price_pence)}</small>
                        <small>Markup {money(o.staff.markup_pence)}</small>
                      </td>
                      <td>
                        <span className={`pill ${chosen ? "green" : o.sent ? "grey" : "amber"}`}>
                          {chosen ? "Chosen" : o.sent ? "Sent" : "Ready"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {detail.step === "awaiting_approval" && detail.can_act && (
        <div className="approve-bar">
          <div>
            <b>
              {detail.options.length} car{detail.options.length === 1 ? "" : "s"} ready to send
            </b>
            <span>Nothing has been sent to the customer yet.</span>
          </div>
          <button type="button" className="btn primary" disabled={working} onClick={approve}>
            {working ? <span className="spinner" /> : null} Approve &amp; send
          </button>
        </div>
      )}
      {problem && <div className="login-error">{problem}</div>}
    </section>
  );
}

/** A short two-note chime, made in the browser (no sound file). Silently skipped if the browser blocks it. */
function chime() {
  try {
    const audio = new (window.AudioContext || window.webkitAudioContext)();
    [880, 1320].forEach((pitch, i) => {
      const note = audio.createOscillator();
      const volume = audio.createGain();
      note.frequency.value = pitch;
      volume.gain.setValueAtTime(0.12, audio.currentTime + i * 0.16);
      volume.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + i * 0.16 + 0.3);
      note.connect(volume).connect(audio.destination);
      note.start(audio.currentTime + i * 0.16);
      note.stop(audio.currentTime + i * 0.16 + 0.3);
    });
  } catch {
    /* no sound */
  }
}

/** Watches for customers choosing a car. Returns the alerts to show; the first look only remembers what is there. */
function useChosenAlerts() {
  const [alerts, setAlerts] = useState([]);
  const seen = useRef(null);

  const check = useCallback(async () => {
    const { enquiries } = await sim.enquiries("chosen");
    if (seen.current === null) {
      seen.current = new Set(enquiries.map((e) => e.id));
      return;
    }
    for (const e of enquiries.filter((one) => !seen.current.has(one.id))) {
      seen.current.add(e.id);
      const detail = await sim.enquiry(e.id);
      setAlerts((now) => [...now, { id: e.id, phone: e.phone, number: detail.chosen_number,
                                    title: detail.chosen_title, staff: detail.assigned_to }]);
      chime();
    }
  }, []);
  usePoll(check, ALERT_MS);

  // the browser tab shows it too, so it is seen from another tab
  useEffect(() => {
    const plain = "Hart Hub · Stock assistant";
    document.title = alerts.length ? `(${alerts.length}) Customer chose a car · Hart Hub` : plain;
    return () => {
      document.title = plain;
    };
  }, [alerts.length]);

  const dismiss = (id) => setAlerts((now) => now.filter((a) => a.id !== id));
  return [alerts, dismiss];
}

/** WhatsApp enquiries as a CRM: menu on the left; queues, the customer list and the open enquiry in the
 *  middle; the customer's WhatsApp on the right (a simulator until the real WhatsApp connection is live). */
export default function SimulatorPage({ user, onSignOut }) {
  const readOnly = user.role === "admin";
  const [tab, setTab] = useState("bot");
  const [list, setList] = useState({ counts: {}, enquiries: [] });
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [phone, setPhone] = useState(null);
  const [search, setSearch] = useState("");
  const [alerts, dismiss] = useChosenAlerts();

  const refresh = useCallback(async () => {
    const [data, one] = await Promise.all([sim.enquiries(tab), selected ? sim.enquiry(selected) : null]);
    setList(data);
    setDetail((now) => (one ? one : selected ? now : null));
  }, [tab, selected]);
  usePoll(refresh, POLL_MS);

  // a click shows the customer straight away from the row already loaded; the rest fills in when it arrives
  const open = (enquiry) => {
    setSelected(enquiry.id);
    setPhone(enquiry.phone);
    setDetail((now) => (now?.id === enquiry.id ? now : { ...enquiry, loading: true, options: [], request: null }));
  };

  // a message from the phone opens that customer's enquiry, in the queue it landed in
  const onActivity = useCallback((enquiry) => {
    if (enquiry) {
      setTab(TAB_OF_STEP[enquiry.step] || "bot");
      setSelected(enquiry.id);
    } else {
      setSelected(null);
    }
  }, []);

  const newCustomer = () => {
    setSelected(null);
    setPhone(testNumber());
  };

  const channel = list.channel || {};
  const simulator = Boolean(channel.simulator);
  const status = simulator
    ? ["sim", "Simulator · fake numbers"]
    : channel.connected
      ? ["live", `Live · ${pretty(channel.number)}${channel.real_customers ? "" : " · test numbers only"}`]
      : ["off", "WhatsApp not connected"];

  const QUEUES = [
    ["bot", "Bot handling", "Chatting, quoting and options"],
    ["person", "Needs a person", "MOTs, viewings, unsure"],
    ["chosen", "Chosen a car", "Hand-over to sales"],
  ];

  return (
    <div className="crm">
      <SideNav user={user} current="whatsapp" onSignOut={onSignOut}
               counts={{ whatsapp: (list.counts.person || 0) + (list.counts.bot || 0) }} />
      <div className="crm-main wa-page">
        <header className="wa-top">
          <div className="wa-title">
            <h1>WhatsApp enquiries</h1>
            {list.channel && (
              <span className={`sim-pill ${status[0]}`}>
                <i /> {status[1]}{readOnly ? " · read only" : ""}
              </span>
            )}
          </div>
          {simulator && !readOnly && (
            <button type="button" className="btn primary" onClick={newCustomer}>
              + New test customer
            </button>
          )}
        </header>

        <div className="queues" role="tablist" aria-label="Queues">
          {QUEUES.map(([key, label, hint]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key}
                    className={`queue ${key}${tab === key ? " on" : ""}`} onClick={() => setTab(key)}>
              <b>{list.counts[key] ?? 0}</b>
              <span>
                <strong>{label}</strong>
                <small>{hint}</small>
              </span>
            </button>
          ))}
        </div>

        {alerts.length > 0 && (
          <div className="sim-alerts" role="alert">
            {alerts.map((a) => (
              <div className="sim-alert" key={a.id}>
                <span className="bell">🔔</span>
                <span>
                  <b>{pretty(a.phone)}</b> chose option {a.number}: <b>{a.title}</b>
                  {a.staff && <> · passed to {a.staff}</>}
                </span>
                <button type="button" className="btn primary small" onClick={() => {
                  setTab("chosen");
                  open(a);
                  dismiss(a.id);
                }}>
                  Open
                </button>
                <button type="button" className="close" aria-label="Dismiss" onClick={() => dismiss(a.id)}>
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="wa-body">
          <EnquiryList list={list} selected={selected} onSelect={open} search={search} setSearch={setSearch} />
          <EnquiryDetail detail={detail} user={user} onChange={setDetail} />
          <aside className="wa-phone" aria-label="Customer's WhatsApp">
            <div className="wa-phone-head">
              <span>Conversation</span>
              <small>What the customer sees on WhatsApp</small>
            </div>
            {phone ? (
              <Phone key={phone} phone={phone} onActivity={onActivity} readOnly={readOnly} live={!simulator} />
            ) : (
              <div className="phone-empty">
                <p>Open an enquiry to see the conversation.</p>
                {simulator && !readOnly && (
                  <button type="button" className="btn ghost small" onClick={newCustomer}>
                    + New test customer
                  </button>
                )}
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
