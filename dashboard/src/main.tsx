import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// placeholder until the AG Studio dashboard is wired in
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <p style={{ color: "#a3acd6", font: "16px system-ui", padding: 24 }}>The dashboard is being built.</p>
  </StrictMode>,
);
