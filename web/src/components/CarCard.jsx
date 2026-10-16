import { useState } from "react";

import { endsInfo, miles, money } from "../lib/format.js";
import { PhotosDialog } from "./Dialogs.jsx";
import Icon from "./Icon.jsx";

const FLAGS = { over_budget: "Over budget", different_model: "Different model", different_colour: "Different colour" };

/** One car offered for the request. `option.customer` is customer-safe; `option.staff` never leaves the portal. */
export default function CarCard({ option, rank, picked, onToggle }) {
  const c = option.customer;
  const s = option.staff;
  const [photosOpen, setPhotosOpen] = useState(false);
  const ends = endsInfo(c.ends_at);
  const specs = [
    ["Year", c.year],
    ["Mileage", c.mileage != null ? `${miles(c.mileage)} mi` : null],
    ["Fuel", c.fuel],
    ["Gearbox", c.gearbox],
    ["Colour", c.colour],
  ].filter(([, value]) => value);

  return (
    <article className={`card${picked ? " picked" : ""}`} data-listing={c.id}>
      <div
        className={c.photo ? "photo" : "photo none"}
        style={c.photo ? { backgroundImage: `url("${encodeURI(c.photo)}")` } : undefined}
      >
        {!c.photo && "No photo yet"}
        <span className="rank" title={`Match ${rank}`}>
          {rank}
        </span>
        {c.ending_soon && <span className="soon">Ending soon</span>}
      </div>

      <div className="main-part">
        <h3>{c.title}</h3>
        <dl className="specs">
          {specs.map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {s.flags.length > 0 && (
          <div className="flags">
            {s.flags.map((flag) => (
              <span className="flag" key={flag}>
                {FLAGS[flag] || flag}
              </span>
            ))}
          </div>
        )}
        {s.match_reason && (
          <div className="reason">
            <Icon name="spark" />
            <span>{s.match_reason}</span>
          </div>
        )}
      </div>

      <div className="side-part">
        <span className="price-label">Price</span>
        <div className="price">{money(c.price_pence)}</div>
        <div className={`ends ${ends.state}`} title={c.available_until}>
          <span className="price-label">Ends</span>
          <div className="date">
            <Icon name="clock" />
            {ends.date}
          </div>
          <div className="left">{ends.left}</div>
        </div>
        <label className="pick">
          <input type="checkbox" checked={picked} onChange={() => onToggle(c.id)} />
          <span className="off">Add to finance quote</span>
          <span className="on">
            <Icon name="check" />
            Added to quote
          </span>
        </label>
      </div>

      <div className="staff">
        <span className="tag">Staff only</span>
        <b>{s.platform}</b>
        <span>{s.registration || "No reg"}</span>
        <span>
          Buy <b>{money(s.buy_price_pence)}</b>
        </span>
        <span>
          <i className={`dot ${s.margin_band}`} />
          Margin <b className={s.margin_band}>{money(s.margin_pence)}</b>
        </span>
        {s.customer_page && (
          <a href={s.customer_page} target="_blank" rel="noopener noreferrer" title="The page a customer sees">
            Customer page ↗
          </a>
        )}
        <button type="button" className="linkish" onClick={() => setPhotosOpen(true)}
                title="Every photo, and which ones customers see">
          Photos
        </button>
        <a href={s.listing_url} target="_blank" rel="noopener noreferrer">
          View listing ↗
        </a>
      </div>
      <PhotosDialog car={photosOpen ? { id: c.id, title: c.title } : null} onClose={() => setPhotosOpen(false)} />
    </article>
  );
}
