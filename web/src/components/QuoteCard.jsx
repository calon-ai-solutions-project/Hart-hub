import { miles, money2 } from "../lib/format.js";
import Icon from "./Icon.jsx";

function kindOf(quote) {
  const name = quote.customer.product_family || quote.staff.product || "";
  if (/hire purchase|\bhp\b/i.test(name)) return "HP";
  if (/pcp|contract purchase/i.test(name)) return "PCP";
  return "";
}

/** The representative example, one figure per row. Every figure is Codeweavers'; nothing is worked out here. */
function Breakdown({ c, kind }) {
  const finalDiffers = c.final_payment_pence != null && c.final_payment_pence !== c.monthly_pence;
  const rows = [
    ["Finance", [kind === "PCP" ? "Personal Contract Purchase" : c.product_family, c.lender].filter(Boolean).join(" · ")],
    ["Cash price", money2(c.cash_price_pence)],
    ["Deposit", money2(c.deposit_pence)],
    ["Amount of credit", money2(c.amount_of_credit_pence)],
    ["Term", `${c.term_months} months`],
    [`${c.regular_payments ?? c.term_months} monthly payments of`, money2(c.monthly_pence), "strong"],
    finalDiffers && [c.optional_final_payment ? "Optional final payment" : "Final payment", money2(c.final_payment_pence)],
    c.charges_pence != null && ["Total charge for credit", money2(c.charges_pence)],
    ["Total amount payable", money2(c.total_payable_pence), "strong"],
    c.annual_mileage && ["Annual mileage", `${miles(c.annual_mileage)} miles`],
    ["Representative APR", `${c.apr}%`, "strong"],
  ].filter(Boolean);
  return (
    <div className="breakdown-body">
      <table>
        <tbody>
          {rows.map(([label, value, tone]) => (
            <tr key={label} className={tone || ""}>
              <th scope="row">{label}</th>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {c.fees && <p className="breakdown-note">{c.fees}</p>}
      {c.disclaimer && <p className="breakdown-note">{c.disclaimer}</p>}
    </div>
  );
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
export default function QuoteCard({ quote }) {
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
            <details className="breakdown">
              <summary>Full breakdown</summary>
              <Breakdown c={c} kind={kind} />
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
