import { useEffect, useState } from "react";
import { api } from "./bridge";
export function ClipJobStatus() {
  const [message, setMessage] = useState("");
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      clearTimeout(timer);
      try {
        const { job } = await (await api("clips")).json();
        if (!alive) return;
        const active = job && ["queued", "generating"].includes(job.status);
        setMessage(
          job
            ? `Scene ${job.scene_id} · ${job.status === "ready" ? "version ready" : job.status}`
            : "",
        );
        timer = setTimeout(refresh, active ? 2000 : 15000);
      } catch {
        if (alive) timer = setTimeout(refresh, 15000);
      }
    }
    const update = () => {
      void refresh();
    };
    window.addEventListener("mpt-clip-job", update);
    void refresh();
    return () => {
      alive = false;
      clearTimeout(timer);
      window.removeEventListener("mpt-clip-job", update);
    };
  }, []);
  return message ? (
    <span aria-live="polite" className="text-xs">
      {message}
    </span>
  ) : null;
}
