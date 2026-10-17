import { useEffect, useMemo, useState } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { AgStudioAiModule } from "ag-studio";
import type { AgStudioApi } from "ag-studio";
import { serverAdapter } from "./adapter";
import { harness } from "./analyst";
import { load, sources, type Analytics } from "./data";
import { initialState } from "./state";
import { darkTheme } from "./theme";
import { widgets } from "./widgets";

const LICENSE = import.meta.env.VITE_AG_STUDIO_LICENSE as string | undefined;

// the owner token, if the owner opened the main page with it, unmasks addresses here the same way
const token = () => { try { return sessionStorage.getItem("cs_owner_token"); } catch { return null; } };

export function App() {
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"view" | "edit">("view");

  useEffect(() => {
    document.body.dataset.agThemeMode = "dark";
    load(token()).then(setData, (e) => setError(String(e.message ?? e)));
  }, []);

  const ai = useMemo(() => (data ? (params: { api: AgStudioApi }) => harness(params.api, serverAdapter(token), data) : undefined), [data]);

  const definition = useMemo(() => (data ? sources(data) : undefined), [data]);

  if (error) return <p className="note">{error} <a href="/">Back to the shop</a></p>;
  if (!data || !definition) return <p className="note">Loading the shop's numbers…</p>;
  return (
    <AgStudioProvider licenseKey={LICENSE} modules={[AgStudioAiModule]}>
      <header className="bar">
        <a href="/" className="back">&larr; The shop</a>
        <b>{data.shop}</b><span className="dim">what the agent asked for, and what Countersign decided</span>
        <button onClick={() => setMode(mode === "view" ? "edit" : "view")}>
          {mode === "view" ? "Edit and ask the assistant" : "Done editing"}
        </button>
      </header>
      <AgStudio style={{ height: "calc(100% - 44px)" }} mode={mode} theme={darkTheme} data={definition} widgets={widgets as never}
        initialState={initialState} ai={ai as never} />
    </AgStudioProvider>
  );
}
