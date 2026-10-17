import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { AgStudioAiModule } from "ag-studio";
import type { AgStudioApi } from "ag-studio";
import { serverAdapter } from "./adapter";
import { harness } from "./analyst";
import { load, loadRuns, sources, type Analytics, type RunRow } from "./data";
import { Loader } from "./Loader";
import { initialState, type Size } from "./state";
import { darkTheme } from "./theme";
import { widgets } from "./widgets";

// What a screen can hold. A phone shows the dashboard alone, stacked. A tablet shows the whole page and no side
// panels. Only a wide screen has room for the builder, which needs the assistant and two panels beside the page.
const PANELS = {
  phone: { edit: { left: [], right: [] }, view: { left: [], right: [] } },
  tablet: { edit: { left: [], right: [] }, view: { left: [], right: [] } },
  desktop: { edit: { left: ["ai"], right: ["edit", "data"] }, view: { right: ["filters"] } },
} as const;
const BUILDER_MIN_WIDTH = 1100;

const sizeOf = (): Size => {
  const w = window.innerWidth;
  return w <= 0 ? "desktop" : w < 700 ? "phone" : w < BUILDER_MIN_WIDTH ? "tablet" : "desktop";
};

const LICENSE = import.meta.env.VITE_AG_STUDIO_LICENSE as string | undefined;

// the owner token, if the owner opened the main page with it, unmasks addresses here the same way
const token = () => { try { return sessionStorage.getItem("cs_owner_token"); } catch { return null; } };

export function App() {
  const [data, setData] = useState<Analytics | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [version, setVersion] = useState(0);
  const [ready, setReady] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [api, setApi] = useState<AgStudioApi | null>(null);
  const [page, setPage] = useState("Live shop");
  const [size, setSize] = useState<Size>(sizeOf);
  const lastPage = useRef("Live shop");

  const fetchAll = useCallback(() => Promise.all([load(token()), loadRuns()]), []);

  useEffect(() => {
    document.body.dataset.agThemeMode = "dark";
    fetchAll().then(([d, r]) => { setData(d); setRuns(r); setReady(true); }, (e) => setError(String(e.message ?? e)));
  }, [fetchAll]);

  // turning a phone or tablet, or resizing a window, re-fits the page to the width it now has
  useEffect(() => {
    const onResize = () => setSize((now) => { const next = sizeOf(); if (next !== now && next !== "desktop") setMode("view"); return next; });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const refresh = () => {
    setRefreshing(true);
    fetchAll().then(([d, r]) => { setData(d); setRuns(r); setVersion((v) => v + 1); }, (e) => setError(String(e.message ?? e))).finally(() => setRefreshing(false));
  };

  const ai = useMemo(() => (data ? (params: { api: AgStudioApi }) => harness(params.api, serverAdapter(token), data, runs) : undefined), [data, runs]);
  const definition = useMemo(() => (data ? sources(data, runs) : undefined), [data, runs]);
  // a new layout starts on the page the visitor was looking at
  const start = useMemo(() => (data ? { ...initialState(size), selectedPageId: lastPage.current } : undefined), [data, size, version]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <p className="note">{error} <a href="/">Back to the shop</a></p>;
  if (!ready || !data || !definition || !start) return <Loader />;
  const canEdit = size === "desktop";
  return (
    <AgStudioProvider licenseKey={LICENSE} modules={[AgStudioAiModule]}>
      <div className="frame">
        <header className="bar">
          <a href="/" className="back">&larr; The shop</a>
          <b>{data.shop}</b>
          <nav className="tabs">
            {["Live shop", "Recorded runs"].map((id) => (
              <button key={id} className={page === id ? "on" : ""} onClick={() => { if (api) { api.setState({ ...api.getState(), selectedPageId: id }); setPage(id); lastPage.current = id; } }}>{id}</button>
            ))}
          </nav>
          <span className="dim">what the agent asked for, and what Countersign decided</span>
          <button className="ghost" onClick={refresh} disabled={refreshing} title="Load the shop's latest numbers">{refreshing ? "Refreshing" : "Refresh"}</button>
          {canEdit && (
            <button onClick={() => setMode(mode === "view" ? "edit" : "view")}>
              {mode === "view" ? "Edit and ask the assistant" : "Done editing"}
            </button>
          )}
        </header>
        {page === "Live shop" && data.actions.length === 0 && (
          <p className="strip">
            Nobody has asked this shop for anything since it was last reset, so there is nothing to chart here yet.
            Send it a request from <a href="/#try">Try the guard</a> or <a href="/#shop">the shop</a>, then press Refresh. Recorded runs has the evidence from real model runs.
          </p>
        )}
        <AgStudio key={`${size}-${version}`} style={{ flex: 1, minHeight: 0 }} mode={canEdit ? mode : "view"} theme={darkTheme} panels={PANELS[size] as never}
          data={definition} widgets={widgets as never} initialState={start} ai={ai as never}
          onApiReady={(e: { api: AgStudioApi }) => { setApi(e.api); setPage(e.api.getState().selectedPageId); }}
          onStateUpdated={() => { if (api) { const p = api.getState().selectedPageId; setPage(p); lastPage.current = p; } }} />
      </div>
    </AgStudioProvider>
  );
}
