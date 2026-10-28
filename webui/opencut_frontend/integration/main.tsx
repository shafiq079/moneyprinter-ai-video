import { ClipJobStatus } from "./clip-job-status";
import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import Editor from "@/app/editor/[project_id]/page";
import {
  bootstrap,
  saveNow,
  downloadBackup,
  sourceToolsUrl,
  status,
  onStatus,
} from "./bridge";
import "./style.css";
import { toast } from "sonner";
function App() {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [, refresh] = useState(0);
  useEffect(() => onStatus(() => refresh((n) => n + 1)), []);
  useEffect(() => {
    bootstrap()
      .then(() => setLoaded(true))
      .catch((e) => setError(e.message));
  }, []);
  return (
    <>
      <div id="mpt-bar">
        <a
          href="/?view=tasks"
          onClick={(event) => {
            if (!loaded) return;
            event.preventDefault();
            saveNow()
              .then(() => window.location.assign("/?view=tasks"))
              .catch((e) => toast.error(e.message));
          }}
        >
          ← MoneyPrinter tasks
        </a>
        <a
          href={sourceToolsUrl()}
          onClick={(event) => {
            if (!loaded) return;
            event.preventDefault();
            saveNow()
              .then(() => window.location.assign(sourceToolsUrl()))
              .catch((e) => toast.error(e.message));
          }}
        >
          Legacy tools
        </a>
        <span>
          {loaded && <ClipJobStatus />} · OpenCut · {status} ·{" "}
          <a href="/opencut/OPENCUT_LICENSE" target="_blank" rel="noreferrer">
            MIT license
          </a>
        </span>
        <button
          disabled={!loaded}
          onClick={() => downloadBackup().catch((e) => toast.error(e.message))}
        >
          Project backup
        </button>
        <button
          disabled={!loaded}
          onClick={() => saveNow().catch((e) => toast.error(e.message))}
        >
          Save project
        </button>
      </div>
      {error ? (
        <div role="alert" style={{ padding: 32 }}>
          {error}
        </div>
      ) : loaded ? (
        <Editor />
      ) : (
        <div style={{ padding: 32 }}>{status}</div>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <ThemeProvider attribute="class" defaultTheme="dark">
    <TooltipProvider>
      <Toaster />
      <App />
    </TooltipProvider>
  </ThemeProvider>,
);
