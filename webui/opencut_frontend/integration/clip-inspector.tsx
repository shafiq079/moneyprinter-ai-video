import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useEditor } from "@/editor/use-editor";
import {
  mediaTimeFromSeconds as time,
  mediaTimeToSeconds as seconds,
} from "@/wasm";
import { processMediaAssets } from "@/media/processing";
import { toast } from "sonner";
import { api, saveNow, taskId } from "./bridge";
import { setCandidatePreview } from "./clip-preview";

type Version = {
  id: string;
  name: string;
  duration: number;
  origin: string;
  prompt: string;
  seed: number;
};
type Scene = {
  id: number;
  label: string;
  prompt: string;
  seed: number;
  provider: string;
  mode: string;
  duration: number;
  versions: Version[];
};
type Job = {
  id: string;
  scene_id: number;
  status: string;
  message: string;
  version_id?: string;
};
export function ClipInspector({
  element,
  trackId,
  sceneId,
}: {
  element: any;
  trackId: string;
  sceneId: number;
}) {
  const editor = useEditor();
  const [scene, setScene] = useState<Scene | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [prompt, setPrompt] = useState("");
  const [seed, setSeed] = useState("0");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [candidate, setCandidate] = useState<string | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const seenJob = useRef("");
  const refreshNow = useRef(() => {});
  const reviewKey = `mpt-clip-review:${taskId}:${element.id}`;
  const cache = useRef(new Map<string, string>());
  const mounted = useRef(true);
  const input = useRef<HTMLInputElement>(null);
  const active = job && ["queued", "generating"].includes(job.status);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    mounted.current = true;
    async function refresh(initial = false) {
      try {
        const data = await (await api("clips")).json();
        if (!alive) return;
        const found = data.scenes.find((s: Scene) => s.id === sceneId);
        setScene(found || null);
        setJob(data.job);
        if (initial && found) {
          setPrompt(element.mptPrompt || found.prompt);
          setSeed(String(element.mptSeed ?? found.seed));
        }
        if (
          data.job?.scene_id === sceneId &&
          data.job.status === "ready" &&
          seenJob.current !== data.job.id
        ) {
          seenJob.current = data.job.id;
          if (
            sessionStorage.getItem(reviewKey) !== data.job.id &&
            element.mptVersionId !== data.job.version_id
          )
            setCandidate(data.job.version_id);
        }
        // Poll only a live job. Idle requests are read-only and infrequent, so a
        // tab reopened during generation can discover progress without remounts.
        timer = setTimeout(
          () => refresh(),
          ["queued", "generating"].includes(data.job?.status) ? 1500 : 10000,
        );
      } catch (e: any) {
        if (alive) {
          setError(e.message);
          timer = setTimeout(() => refresh(), 10000);
        }
      }
    }
    refreshNow.current = () => {
      clearTimeout(timer);
      void refresh();
    };
    refresh(true);
    return () => {
      alive = false;
      mounted.current = false;
      clearTimeout(timer);
      refreshNow.current = () => {};
      setCandidatePreview(null);
      for (const url of cache.current.values()) URL.revokeObjectURL(url);
      cache.current.clear();
    };
  }, [sceneId, element.id]);
  useEffect(() => {
    if (!scene) return;
    const version = scene.versions.find((v) => v.id === element.mptVersionId);
    setPrompt(version?.prompt || element.mptPrompt || scene.prompt);
    setSeed(String(version?.seed ?? element.mptSeed ?? scene.seed));
  }, [element.mptVersionId, scene?.id]);
  async function reload() {
    const data = await (await api("clips")).json();
    if (mounted.current) {
      setScene(data.scenes.find((s: Scene) => s.id === sceneId));
      setJob(data.job);
    }
  }
  async function action(name: string, run: () => Promise<void>) {
    setBusy(name);
    setError("");
    try {
      await run();
    } catch (e: any) {
      if (mounted.current) setError(e.message);
    } finally {
      if (mounted.current) {
        setBusy("");
        refreshNow.current();
        window.dispatchEvent(new Event("mpt-clip-job"));
      }
    }
  }
  async function video(version: Version) {
    let url = cache.current.get(version.id);
    if (!url) {
      url = URL.createObjectURL(
        await (await api(`clips/${sceneId}/${version.id}`)).blob(),
      );
      if (!mounted.current) {
        URL.revokeObjectURL(url);
        throw new Error("Clip selection changed.");
      }
      cache.current.set(version.id, url);
      setUrls((previous) => ({ ...previous, [version.id]: url! }));
    }
    return url;
  }
  async function preview(version: Version) {
    const url = await video(version);
    editor.playback.pause();
    setCandidate(version.id);
    setCandidatePreview({ url, name: version.name });
  }
  async function apply(version: Version) {
    const url = await video(version);
    editor.playback.pause();
    setCandidatePreview({ url, name: version.name });
    const file = new File(
      [await (await fetch(url)).blob()],
      `Scene-${sceneId}-${version.name}.mp4`,
      { type: "video/mp4" },
    );
    const processed = await processMediaAssets({ files: [file] });
    if (!processed[0]) throw new Error("This browser could not read the clip.");
    // Re-read the exact occurrence after asynchronous media work. A split,
    // deletion or intervening undo must never change another timeline clip.
    const current: any = editor.timeline.getElementsWithTracks({
      elements: [{ trackId, elementId: element.id }],
    })[0]?.element;
    if (
      !current ||
      current.mediaId !== element.mediaId ||
      current.duration !== element.duration ||
      current.trimStart !== element.trimStart ||
      current.trimEnd !== element.trimEnd
    )
      throw new Error(
        "The selected clip changed. Select it again before applying.",
      );
    const sourceEnd = current.sourceDuration
      ? seconds({ time: current.sourceDuration }) -
        seconds({ time: current.trimEnd })
      : seconds({ time: current.trimStart }) +
        seconds({ time: current.duration });
    const duration = processed[0].duration || 0;
    if (duration + 0.001 < sourceEnd)
      throw new Error(
        `This version needs ${sourceEnd.toFixed(2)}s of footage, but contains ${duration.toFixed(2)}s. Adjust the clip trim or choose a longer version.`,
      );
    const asset = await editor.media.addMediaAsset({
      projectId: editor.project.getActive()!.metadata.id,
      asset: processed[0],
    });
    if (!asset || !mounted.current)
      throw new Error(
        "Clip selection changed; no timeline replacement was made.",
      );
    const latest: any = editor.timeline.getElementsWithTracks({
      elements: [{ trackId, elementId: element.id }],
    })[0]?.element;
    if (
      !latest ||
      latest.mediaId !== current.mediaId ||
      latest.duration !== current.duration ||
      latest.trimStart !== current.trimStart ||
      latest.trimEnd !== current.trimEnd
    )
      throw new Error(
        "The clip changed while importing. Select it again before applying.",
      );
    editor.timeline.updateElements({
      updates: [
        {
          trackId,
          elementId: element.id,
          patch: {
            mediaId: asset.id,
            sourceDuration: time({ seconds: duration }),
            trimEnd: time({ seconds: Math.max(0, duration - sourceEnd) }),
            mptVersionId: version.id,
            mptPrompt: version.prompt,
            mptSeed: version.seed,
          } as any,
        },
      ],
    });
    if (job) sessionStorage.setItem(reviewKey, job.id);
    setCandidatePreview(null);
    setCandidate(null);
    await saveNow();
    toast.success("Selected clip updated. Undo is available in OpenCut.");
  }
  if (!scene)
    return (
      <div className="p-4 text-sm" role="status">
        {error || "Loading clip controls…"}
      </div>
    );
  return (
    <div className="space-y-4 p-4 text-sm" aria-label="AI clip inspector">
      <div>
        <h2 className="font-medium">AI Clip · Scene {sceneId}</h2>
        <p className="text-muted-foreground mt-1 line-clamp-3 text-xs">
          {scene.label}
        </p>
      </div>
      <div className="text-muted-foreground flex justify-between text-xs">
        <span>{scene.provider}</span>
        <span>
          {scene.duration.toFixed(1)}s · {scene.mode}
        </span>
      </div>
      <div className="space-y-2">
        <label htmlFor={`prompt-${element.id}`} className="font-medium">
          Describe this clip
        </label>
        <Textarea
          id={`prompt-${element.id}`}
          value={prompt}
          maxLength={4000}
          rows={5}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe the scene you want…"
        />
      </div>
      <div className="space-y-2">
        <Button
          className="w-full"
          disabled={!!busy || !!active || !prompt.trim()}
          onClick={() =>
            action("generate", async () => {
              setJob(
                await (
                  await api(`clips/${sceneId}/generate`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ prompt, seed: Number(seed) }),
                  })
                ).json(),
              );
            })
          }
        >
          Regenerate clip
        </Button>
        <Button
          variant="outline"
          className="w-full"
          disabled={!!busy || !!active || !prompt.trim()}
          onClick={() =>
            action("variation", async () => {
              setJob(
                await (
                  await api(`clips/${sceneId}/generate`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      prompt,
                      seed: Number(seed),
                      variation: true,
                    }),
                  })
                ).json(),
              );
            })
          }
        >
          New variation
        </Button>
      </div>
      <details className="rounded-md border p-3">
        <summary className="cursor-pointer text-xs font-medium">
          Advanced
        </summary>
        <div className="mt-3 space-y-2">
          <label htmlFor={`seed-${element.id}`} className="text-xs">
            Seed
          </label>
          <Input
            id={`seed-${element.id}`}
            type="number"
            min={0}
            max={2147483647}
            step={1}
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
          />
          <p className="text-muted-foreground text-xs">
            Same seed keeps the recipe repeatable. New variation chooses another
            seed.
          </p>
        </div>
      </details>
      {job && (
        <div className="space-y-2 rounded-md border p-3" role="status">
          <p className="text-xs">
            {job.scene_id !== sceneId ? `Scene ${job.scene_id}: ` : ""}
            {job.message}
          </p>
          {active && (
            <Button
              size="sm"
              variant="ghost"
              disabled={!!busy}
              onClick={() =>
                action("cancel", async () => {
                  await api("clips/cancel", { method: "POST" });
                  await reload();
                })
              }
            >
              Cancel generation
            </Button>
          )}
        </div>
      )}
      {busy && (
        <p className="text-muted-foreground text-xs" role="status">
          {busy === "upload"
            ? "Processing upload…"
            : busy === "apply"
              ? "Updating selected clip…"
              : "Working…"}
        </p>
      )}
      {error && (
        <p
          className="text-destructive rounded-md border p-3 text-xs"
          role="alert"
        >
          {error}
        </p>
      )}
      {candidate && scene.versions.find((v) => v.id === candidate) && (
        <div className="space-y-2 rounded-md border p-3">
          <p className="font-medium">Ready to review</p>
          {urls[candidate] && (
            <video
              src={urls[candidate]}
              muted
              preload="metadata"
              className="max-h-28 w-full rounded object-contain"
              aria-label="Candidate thumbnail"
            />
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={!!busy}
              onClick={() =>
                action("preview", () =>
                  preview(scene.versions.find((v) => v.id === candidate)!),
                )
              }
            >
              Preview
            </Button>
            <Button
              size="sm"
              disabled={!!busy}
              onClick={() =>
                action("apply", () =>
                  apply(scene.versions.find((v) => v.id === candidate)!),
                )
              }
            >
              Use this version
            </Button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              if (job) sessionStorage.setItem(reviewKey, job.id);
              setCandidate(null);
              setCandidatePreview(null);
            }}
          >
            Keep current
          </Button>
        </div>
      )}
      <details className="border-t pt-3">
        <summary className="cursor-pointer font-medium">
          Versions ({scene.versions.length})
        </summary>
        <div className="mt-3 space-y-3">
          {[...scene.versions].reverse().map((v) => (
            <div key={v.id} className="space-y-2 rounded-md border p-2">
              <div className="flex items-center gap-2">
                {urls[v.id] && (
                  <video
                    src={urls[v.id]}
                    muted
                    preload="metadata"
                    className="h-12 w-16 rounded object-cover"
                  />
                )}
                <div className="min-w-0">
                  <p className="truncate text-xs">
                    {v.name}
                    {element.mptVersionId === v.id ? " · Current" : ""}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {v.duration.toFixed(1)}s · {v.origin}
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!!busy}
                  onClick={() => action("preview", () => preview(v))}
                >
                  Preview
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!!busy || element.mptVersionId === v.id}
                  onClick={() => action("apply", () => apply(v))}
                >
                  Use this version
                </Button>
              </div>
            </div>
          ))}
        </div>
      </details>
      <input
        ref={input}
        hidden
        type="file"
        accept="video/mp4"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file)
            action("upload", async () => {
              if (file.size > 100 * 1024 * 1024)
                throw new Error("Upload an MP4 smaller than 100 MiB.");
              const data = await (
                await api(`clips/${sceneId}/upload`, {
                  method: "POST",
                  body: file,
                })
              ).json();
              await reload();
              if (mounted.current) setCandidate(data.version_id);
            });
        }}
      />
      <Button
        variant="outline"
        className="w-full"
        disabled={!!busy || !!active}
        onClick={() => input.current?.click()}
      >
        Upload replacement video
      </Button>
      <p className="text-muted-foreground text-xs">
        Changes apply to this selected clip only. Timing, captions, narration
        and other clips stay in place.
      </p>
    </div>
  );
}
