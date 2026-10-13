import { miles, money2 } from "../lib/format.js";
import Icon from "./Icon.jsx";

function kindOf(quote) {
  const name = quote.customer.product_family || quote.staff.product || "";
  if (/hire purchase|\bhp\b/i.test(name)) return "HP";
  if (/pcp|contract purchase/i.test(name)) return "PCP";
  return "";
}

function Dots() {
  return (
    <span className="typing">
      <i />
      <i />
      <i />
    </span>
  );
}

/** A Codeweavers finance quote. Every figure shown came from Codeweavers; nothing is worked out here. */
export default function QuoteCard({ quote, onPreview }) {
  const c = quote.customer;
  const s = quote.staff;
  const done = quote.status === "done";
  const failed = quote.status === "failed";
  const kind = kindOf(quote);
  const look = done ? (kind === "HP" ? "hp" : "pcp") : failed ? "fail" : "wait";

  const figures = done
    ? [
        ["Cash price", money2(c.cash_price_pence)],
        ["Deposit", money2(c.deposit_pence)],
        ["Amount of credit", money2(c.amount_of_credit_pence)],
        ["Total payable", money2(c.total_payable_pence)],
        c.optional_final_payment && ["Optional final payment", money2(c.final_payment_pence)],
        c.annual_mileage && ["Annual mileage", `${miles(c.annual_mileage)} miles`],
      ].filter(Boolean)
    : [];

  return (
    <article className={`quote ${look}`}>
      <div className="pay">
        <span className="kind">{done ? kind || "Finance" : failed ? "No quote" : "Quoting"}</span>
        <div className="monthly">{done ? money2(c.monthly_pence) : "–"}</div>
        <div className="per">{done ? "per month" : failed ? "no figure available" : "waiting for Codeweavers"}</div>
        {done && (
          <div className="terms">
            <div>
              <b>{c.term_months}</b>
              <span>Months</span>
            </div>
            <div>
              <b>{c.apr}%</b>
              <span>APR rep.</span>
            </div>
          </div>
        )}
      </div>

      <div className="figures">
        <div>
          {done && (
            <div className="lender">
              {c.lender} · {c.product_family}
            </div>
          )}
          <h3>{c.title}</h3>
        </div>
        {done && (
          <>
            <dl>
              {figures.map(([name, value]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <details>
              <summary>Full breakdown</summary>
              <p>{c.example}</p>
              {c.fees && <p>{c.fees}</p>}
              <p>{c.disclaimer}</p>
            </details>
          </>
        )}
        {failed && <div className="follow">{c.message}</div>}
        {!done && !failed && (
          <div className="state waiting">
            <Dots />
            {c.message}
          </div>
        )}
      </div>

      <div className="doc">
        <span className="price-label">Quote document</span>
        {done && quote.pdf_url ? (
          <>
            <button type="button" className="btn primary small" onClick={() => onPreview(quote)}>
              <Icon name="file" />
              Preview PDF
            </button>
            <a className="btn ghost small" href={`${quote.pdf_url}?download=1`}>
              Download
            </a>
            <div className="hintline">Codeweavers’ own PDF, as the customer would receive it.</div>
          </>
        ) : (
          <div className="none">
            {done
              ? "Codeweavers did not return a document for this quote. Request it again to try."
              : failed
                ? "No document: the quote could not be made."
                : "The PDF arrives with the quote."}
          </div>
        )}
      </div>

      <div className="staff">
        {done && s.note && (
          <div className="why">
            <Icon name="alert" />
            <span>{s.note}</span>
          </div>
        )}
        <span className="tag">Staff only</span>
        {failed ? (
          <span>{s.error}</span>
        ) : (
          <>
            <b>{s.registration}</b>
            <span>Quoted at {miles(s.mileage_sent)} miles</span>
            <span>{s.product}</span>
            {(!done || kind !== "PCP") && <span>Credit: {s.credit_tier}</span>}
            {s.quote_ref && <span>Ref {s.quote_ref.slice(0, 8)}</span>}
          </>
        )}
      </div>
    </article>
  );
}
