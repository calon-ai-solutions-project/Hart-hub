import { useEffect, useRef, useState } from "react";

import logo from "../assets/logo.png";
import { endsInfo, miles, money } from "../lib/format.js";
import Icon from "./Icon.jsx";

/** The public "more photos" page a customer opens from WhatsApp. No login; customer fields only. */
export default function PublicCarPage({ token }) {
  const [data, setData] = useState(null);
  const [problem, setProblem] = useState("");
  const [shown, setShown] = useState(0);
  const track = useRef(null);
  const thumbs = useRef(null);
  const sliding = useRef(null); // {to, timer} while a click's slide is running

  // show photo `index`: the big picture slides to it and its thumbnail comes into view
  function goTo(index) {
    const count = data?.photos.length || 0;
    if (!count || !track.current) return;
    const next = (index + count) % count;
    clearTimeout(sliding.current?.timer);
    // while it slides, the scroll position passes other photos: the counter keeps the target
    sliding.current = { to: next, timer: setTimeout(() => (sliding.current = null), 600) };
    track.current.scrollTo({ left: next * track.current.clientWidth, behavior: "smooth" });
    setShown(next);
  }
  const current = () => sliding.current?.to ?? shown;

  useEffect(() => {
    thumbs.current?.children[shown]?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [shown]);

  useEffect(() => {
    fetch(`/api/public/cars/${encodeURIComponent(token)}`)
      .then(async (response) => {
        if (response.status === 404) throw new Error("This link is not valid.");
        if (!response.ok) throw new Error("This page could not be loaded. Please try again in a moment.");
        setData(await response.json());
      })
      .catch((error) => setProblem(error.message));
  }, [token]);

  useEffect(() => {
    if (data?.car) document.title = `${data.car.title} · Hart Group`;
  }, [data]);

  const reply =
    data?.whatsapp &&
    `https://wa.me/${data.whatsapp}?text=${encodeURIComponent(
      data.car ? `Hi, I'm interested in the ${data.car.title}` : "Hi, I'd like to see some other cars",
    )}`;

  return (
    <div className="public">
      <header className="public-top">
        <img src={logo} alt="The Hart Group Automotive" />
      </header>

      <main className="public-main">
        {!data && !problem && <div className="skeleton tall" />}
        {problem && <p className="public-note">{problem}</p>}

        {data && !data.available && (
          <div className="public-note">
            <h1>This car is no longer available</h1>
            <p>It has sold or the deal has ended. Message us and we’ll find you something similar.</p>
          </div>
        )}

        {data?.car && (
          <>
            <section
              className="gallery"
              aria-label="Photos"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "ArrowRight") goTo(current() + 1);
                if (event.key === "ArrowLeft") goTo(current() - 1);
              }}
            >
              <div
                className="gallery-track"
                ref={track}
                onScroll={(event) => {
                  if (sliding.current) return; // a click's slide: the counter already shows where it goes
                  const box = event.currentTarget;
                  setShown(Math.round(box.scrollLeft / box.clientWidth));
                }}
              >
                {data.photos.length === 0 && <div className="gallery-empty">Photos coming soon</div>}
                {data.photos.map((photo, index) => (
                  <img key={photo.full} src={photo.full} alt={`${data.car.title}, photo ${index + 1}`}
                       loading={index < 2 ? "eager" : "lazy"} />
                ))}
              </div>
              {data.photos.length > 1 && (
                <>
                  <button type="button" className="gallery-arrow prev" aria-label="Previous photo"
                          onClick={() => goTo(current() - 1)}>
                    ‹
                  </button>
                  <button type="button" className="gallery-arrow next" aria-label="Next photo"
                          onClick={() => goTo(current() + 1)}>
                    ›
                  </button>
                  <span className="gallery-count">
                    {shown + 1} / {data.photos.length}
                  </span>
                </>
              )}
            </section>
            {data.photos.length > 1 && (
              <div className="gallery-thumbs" ref={thumbs}>
                {data.photos.map((photo, index) => (
                  <button
                    type="button"
                    key={photo.thumb}
                    className={index === shown ? "on" : ""}
                    aria-label={`Photo ${index + 1}`}
                    aria-current={index === shown}
                    onClick={() => goTo(index)}
                  >
                    <img src={photo.thumb} alt="" loading="lazy" />
                  </button>
                ))}
              </div>
            )}

            <section className="public-card">
              <h1>{data.car.title}</h1>
              <dl className="specs">
                {[
                  ["Year", data.car.year],
                  ["Mileage", data.car.mileage != null ? `${miles(data.car.mileage)} mi` : null],
                  ["Fuel", data.car.fuel],
                  ["Gearbox", data.car.gearbox],
                  ["Colour", data.car.colour],
                ]
                  .filter(([, value]) => value)
                  .map(([name, value]) => (
                    <div key={name}>
                      <dt>{name}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
              </dl>
              <div className="public-price">
                <span className="price-label">Price</span>
                <b>{money(data.car.price_pence)}</b>
              </div>
              <div className={`ends ${endsInfo(data.car.ends_at).state}`}>
                <div className="date">
                  <Icon name="clock" />
                  {data.car.available_until}
                </div>
              </div>
              <p className="public-fine">{data.disclaimer}</p>
            </section>
          </>
        )}
      </main>

      {reply && (
        <a className="public-reply" href={reply} target="_blank" rel="noopener noreferrer">
          Reply on WhatsApp
        </a>
      )}
    </div>
  );
}
