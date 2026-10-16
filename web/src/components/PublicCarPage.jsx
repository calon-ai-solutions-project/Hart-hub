import { useCallback, useEffect, useRef, useState } from "react";

import logo from "../assets/logo.png";
import { endsInfo, miles } from "../lib/format.js";
import Icon from "./Icon.jsx";

const Camera = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
    <circle cx="12" cy="13" r="3.5" />
  </svg>
);
const Expand = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  </svg>
);

/** The photos: one large picture, arrows, a count, a strip of thumbnails, swipe on phones, and a full-screen view. */
function Gallery({ photos, title }) {
  const [index, setIndex] = useState(0);
  const [full, setFull] = useState(false);
  const thumbs = useRef(null);
  const touch = useRef(null);
  const count = photos.length;

  const go = useCallback((to) => setIndex(((to % count) + count) % count), [count]);

  // keep the chosen thumbnail in view
  useEffect(() => {
    const strip = thumbs.current;
    const thumb = strip?.children[index];
    if (strip && thumb) strip.scrollTo({ left: thumb.offsetLeft - strip.clientWidth / 2 + thumb.clientWidth / 2, behavior: "smooth" });
  }, [index]);

  // arrows and Esc work on the page, and in the full-screen view
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "ArrowRight") go(index + 1);
      if (event.key === "ArrowLeft") go(index - 1);
      if (event.key === "Escape") setFull(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, index]);

  useEffect(() => {
    document.body.style.overflow = full ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [full]);

  const swipe = {
    onTouchStart: (event) => (touch.current = event.touches[0].clientX),
    onTouchEnd: (event) => {
      if (touch.current == null) return;
      const moved = event.changedTouches[0].clientX - touch.current;
      if (Math.abs(moved) > 40) go(index + (moved < 0 ? 1 : -1));
      touch.current = null;
    },
  };

  if (!count) return <div className="gallery-empty">Photos coming soon</div>;
  const photo = photos[index];
  return (
    <section className="pg" aria-label="Photos">
      <div className="pg-stage" {...swipe}>
        <img key={photo.full} className="pg-main" src={photo.full} alt={`${title}, photo ${index + 1} of ${count}`}
             onClick={() => setFull(true)} />
        {count > 1 && (
          <>
            <button type="button" className="pg-arrow prev" aria-label="Previous photo" onClick={() => go(index - 1)}>‹</button>
            <button type="button" className="pg-arrow next" aria-label="Next photo" onClick={() => go(index + 1)}>›</button>
          </>
        )}
        <span className="pg-count"><Camera /> {index + 1} / {count}</span>
        <button type="button" className="pg-expand" onClick={() => setFull(true)} aria-label="View full screen">
          <Expand /> <span>Full screen</span>
        </button>
      </div>

      {count > 1 && (
        <div className="pg-thumbs" ref={thumbs}>
          {photos.map((one, i) => (
            <button type="button" key={one.thumb} className={i === index ? "on" : ""} aria-label={`Photo ${i + 1}`}
                    aria-current={i === index} onClick={() => go(i)}>
              <img src={one.thumb} alt="" loading="lazy" />
            </button>
          ))}
        </div>
      )}

      {full && (
        <div className="pg-full" role="dialog" aria-modal="true" aria-label={`${title} photos`} {...swipe}>
          <div className="pg-full-top">
            <span>{index + 1} / {count}</span>
            <button type="button" onClick={() => setFull(false)} aria-label="Close">×</button>
          </div>
          <img key={`full-${photo.full}`} src={photo.full} alt={`${title}, photo ${index + 1} of ${count}`} />
          {count > 1 && (
            <>
              <button type="button" className="pg-arrow prev" aria-label="Previous photo" onClick={() => go(index - 1)}>‹</button>
              <button type="button" className="pg-arrow next" aria-label="Next photo" onClick={() => go(index + 1)}>›</button>
            </>
          )}
        </div>
      )}
    </section>
  );
}

/** The public "more photos" page a customer opens from WhatsApp. No login; customer fields only.
 *  No WhatsApp button: the customer is already in the WhatsApp chat and replies there. */
export default function PublicCarPage({ token }) {
  const [data, setData] = useState(null);
  const [problem, setProblem] = useState("");

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

  const specs = data?.car
    ? [
        ["Year", data.car.year],
        ["Mileage", data.car.mileage != null ? `${miles(data.car.mileage)} miles` : null],
        ["Fuel", data.car.fuel],
        ["Gearbox", data.car.gearbox],
        ["Colour", data.car.colour],
        ["Body", data.car.body],
      ].filter(([, value]) => value)
    : [];

  return (
    <div className="public">
      <header className="public-top">
        <img src={logo} alt="The Hart Group Automotive" />
      </header>

      <main className="public-main wide">
        {!data && !problem && <div className="skeleton tall" />}
        {problem && <p className="public-note">{problem}</p>}

        {data && !data.available && (
          <div className="public-note">
            <h1>This car is no longer available</h1>
            <p>It has sold or the deal has ended. Message us and we’ll find you something similar.</p>
          </div>
        )}

        {data?.car && (
          <div className="listing">
            <Gallery photos={data.photos} title={data.car.title} />

            <aside className="listing-info">
              <section className="public-card">
                <p className="listing-eyebrow">Hart Group Automotive</p>
                <h1>{data.car.title}</h1>
                <div className={`listing-ends ${endsInfo(data.car.ends_at).state}`}>
                  <Icon name="clock" />
                  <span>{data.car.available_until}</span>
                </div>
                <dl className="listing-specs">
                  {specs.map(([name, value]) => (
                    <div key={name}>
                      <dt>{name}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="public-fine">{data.disclaimer}</p>
              </section>
            </aside>
          </div>
        )}
      </main>

    </div>
  );
}
