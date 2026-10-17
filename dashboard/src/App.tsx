import { useEffect, useMemo, useState } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { AgStudioAiModule } from "ag-studio";
import type { AgStudioApi } from "ag-studio";
import { serverAdapter } from "./adapter";
import { harness } from "./analyst";
import { load, loadRuns, sources, type Analytics, type RunRow } from "./data";
import { initialState } from "./state";
import { darkTheme } from "./theme";
import { widgets } from "./widgets";

// In edit mode the assistant sits on the left and the builder panels on the right, so the page keeps room to be seen
const PANELS = { edit: { left: ["ai"], right: ["edit", "data"] }, view: { right: ["filters"] } } as never;
// a phone has no room for a side panel, so it shows the dashboard alone
const PHONE_PANELS = { edit: { left: [], right: [] }, view: { left: [], right: [] } } as never;

const LICENSE = import.meta.env.VITE_AG_STUDIO_LICENSE as string | undefined;

// the owner token, if the owner opened the main page with it, unmasks addresses here the same way
const token = () => { try { return sessionStorage.getItem("cs_owner_token"); } catch { return null; } };

export function App() {
  const [data, setData] = useState<Analytics | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [api, setApi] = useState<AgStudioApi | null>(null);
  const [page, setPage] = useState("");

  useEffect(() => {
    document.body.dataset.agThemeMode = "dark";
    Promise.all([load(token()), loadRuns()]).then(([d, r]) => { setData(d); setRuns(r); setReady(true); }, (e) => setError(String(e.message ?? e)));
  }, []);

  const ai = useMemo(() => (data ? (params: { api: AgStudioApi }) => harness(params.api, serverAdapter(token), data, runs) : undefined), [data, runs]);

  const definition = useMemo(() => (data ? sources(data, runs) : undefined), [data, runs]);
  const phone = window.innerWidth > 0 && window.innerWidth < 700;
  const start = useMemo(() => (data ? initialState(data.actions.length > 0, phone) : undefined), [data, phone]);

  if (error) return <p className="note">{error} <a href="/">Back to the shop</a></p>;
  if (!ready || !data || !definition || !start) return <p className="note">Loading the shop's numbers…</p>;
  return (
    <AgStudioProvider licenseKey={LICENSE} modules={[AgStudioAiModule]}>
      <div className="frame">
      <header className="bar">
        <a href="/" className="back">&larr; The shop</a>
        <b>{data.shop}</b>
        <nav className="tabs">
          {["Live shop", "Recorded runs"].map((id) => (
            <button key={id} className={page === id ? "on" : ""} onClick={() => { if (api) { api.setState({ ...api.getState(), selectedPageId: id }); setPage(id); } }}>{id}</button>
          ))}
        </nav>
        <span className="dim">what the agent asked for, and what Countersign decided</span>
        <button className="editbtn" onClick={() => setMode(mode === "view" ? "edit" : "view")}>
          {mode === "view" ? "Edit and ask the assistant" : "Done editing"}
        </button>
      </header>
      {page === "Live shop" && data.actions.length === 0 && (
        <p className="strip">
          Nobody has asked this shop for anything since it was last reset, so there is nothing to chart here yet.
          Send it a request from <a href="/#try">Try the guard</a> or <a href="/#shop">the shop</a> and reload, or open Recorded runs for the evidence from real model runs.
        </p>
      )}
      <AgStudio style={{ flex: 1, minHeight: 0 }} mode={mode} theme={darkTheme} panels={phone ? PHONE_PANELS : PANELS} data={definition} widgets={widgets as never}
        initialState={start} ai={ai as never}
        onApiReady={(e: { api: AgStudioApi }) => { setApi(e.api); setPage(e.api.getState().selectedPageId); }}
        onStateUpdated={() => { if (api) setPage(api.getState().selectedPageId); }} />
      </div>
    </AgStudioProvider>
  );
}
