import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import "./styles/app.css";
import "./styles/login.css";
import "./styles/public.css";
import "./styles/sim.css";
import "./styles/home.css";
import "./styles/crm.css";
import "./styles/wa.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
