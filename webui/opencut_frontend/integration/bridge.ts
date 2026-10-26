import { initFonts, importedFont, loadFonts } from "./fonts";
import { EditorCore } from "@/core";
import { storageService } from "@/services/storage/service";
import { processMediaAssets } from "@/media/processing";
import {
  buildElementFromMedia,
  buildTextElement,
} from "@/timeline/element-utils";
import { mediaTimeFromSeconds as time } from "@/wasm";
import { toast } from "sonner";
import { initializeGpuRenderer } from "@/services/renderer/gpu-renderer";
import { FONT_SIZE_SCALE_REFERENCE } from "@/text/typography";

const parameters = new URLSearchParams(window.location.hash.slice(1));
const token =
  parameters.get("token") ||
  sessionStorage.getItem("mpt-opencut-session") ||
  "";
if (token) sessionStorage.setItem("mpt-opencut-session", token);
export let taskId = "";
try {
  const raw = JSON.parse(
    atob(token.split(".")[0].replace(/-/g, "+").replace(/_/g, "/")),
  );
  if (/^[A-Za-z0-9_-]{1,128}$/.test(raw.task)) taskId = raw.task;
} catch {}
export function sourceToolsUrl() {
  return "/?editor=" + encodeURIComponent(taskId) + "&legacy=1";
}
window.history.replaceState(
  null,
  "",
  window.location.pathname + window.location.search,
);
export let status = "Loading saved project…";
let notify = () => {};
export function onStatus(callback: () => void) {
  notify = callback;
  return () => {
    notify = () => {};
  };
}
function setStatus(message: string) {
  status = message;
  notify();
}
export async function api(path: string, init: RequestInit = {}) {
  const response = await fetch("/opencut/api/" + path, {
    ...init,
    headers: { ...init.headers, Authorization: "Bearer " + token },
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(data.detail || "OpenCut request failed");
  }
  return response;
}
const known = new Map<string, string>();
let saving: Promise<any> = Promise.resolve();
let ready = false;
let pendingSaves = 0;
let saveFailed = false;
window.addEventListener("beforeunload", (event) => {
  if (pendingSaves || saveFailed) {
    event.preventDefault();
    event.returnValue = "";
  }
});
let revision = "missing";
function serialize(project: any) {
  return JSON.parse(
    JSON.stringify(project, (key, value) =>
      key === "buffer" ? undefined : value,
    ),
  );
}
async function persist(project: any) {
  setStatus("Saving project…");
  const editor = EditorCore.getInstance();
  const media = [];
  for (const item of editor.media.getAssets()) {
    let digest = known.get(item.id);
    if (!digest) {
      const bytes = await item.file.arrayBuffer();
      digest = Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      )
        .map((v) => v.toString(16).padStart(2, "0"))
        .join("");
      await api("media/" + digest, { method: "PUT", body: bytes });
      known.set(item.id, digest);
    }
    const { file, url, thumbnailUrl, ...metadata } = item;
    media.push({
      ...metadata,
      blob: digest,
      mime: file.type,
      lastModified: file.lastModified,
    });
  }
  const saved = await api("project", {
    method: "PUT",
    headers: { "Content-Type": "application/json", "If-Match": revision },
    body: JSON.stringify({ project: serialize(project), media }),
  });
  revision = (await saved.json()).revision;
  setStatus("Saved to this task");
}
function schedule(project: any) {
  pendingSaves++;
  saving = saving
    .catch(() => {})
    .then(() => persist(project))
    .then(() => {
      saveFailed = false;
    })
    .catch((error) => {
      saveFailed = true;
      throw error;
    })
    .finally(() => {
      pendingSaves--;
    });
  saving.catch((error) => {
    setStatus("Save failed — " + error.message);
    toast.error("Project save failed", { description: error.message });
  });
  return saving;
}
export async function saveNow() {
  await EditorCore.getInstance().project.saveCurrentProject();
  await saving;
}
function dates(project: any) {
  return {
    ...project,
    metadata: {
      ...project.metadata,
      createdAt: new Date(project.metadata.createdAt),
      updatedAt: new Date(project.metadata.updatedAt),
    },
    scenes: project.scenes.map((s: any) => ({
      ...s,
      createdAt: new Date(s.createdAt),
      updatedAt: new Date(s.updatedAt),
    })),
  };
}
function element(type: string, asset: any, start: number, duration: number) {
  return {
    ...buildElementFromMedia({
      mediaId: asset.id,
      mediaType: type as any,
      name: asset.name,
      startTime: time({ seconds: start }),
      duration: time({ seconds: duration }),
    }),
    id: crypto.randomUUID(),
  };
}
export async function bootstrap() {
  if (!token)
    throw new Error("Open this editor from MoneyPrinter Task Manager.");
  await initFonts();
  await initializeGpuRenderer();
  const response = await api("session");
  const data = await response.json();
  revision = data.revision;
  taskId = data.task_id;
  const editor = EditorCore.getInstance();
  let project: any;
  if (data.mode === "restore") {
    project = dates(data.project);
    project.metadata.id = "mpt-" + data.task_id;
    setStatus("Restoring saved media…");
    for (const record of data.media) {
      const response = await api("media/" + record.blob);
      const file = new File([await response.blob()], record.name, {
        type: record.mime,
        lastModified: record.lastModified,
      });
      const { blob, mime, ...metadata } = record;
      await storageService.saveMediaAsset({
        projectId: project.metadata.id,
        mediaAsset: { ...metadata, file },
      });
      known.set(record.id, record.blob);
    }
    await storageService.saveProject({ project });
  } else {
    const seed = data.seed;
    setStatus("Importing saved video and audio…");
    const temporaryId = await editor.project.createNewProject({
      name: seed.name,
    });
    project = editor.project.getActive();
    const id = "mpt-" + seed.task_id;
    project.metadata.id = id;
    editor.project.setActiveProject({ project });
    await storageService.deleteProject({ id: temporaryId });
    const assets = new Map<string, any>();
    for (const [key, record] of Object.entries(seed.resources) as any) {
      setStatus("Importing " + record.name + "…");
      const response = await api("source/" + key);
      const sourceScene = seed.scenes.find((s: any) => s.asset === key);
      const displayName = sourceScene
        ? `Scene ${sourceScene.id}.mp4`
        : record.name;
      const file = new File([await response.blob()], displayName, {
        type:
          response.headers.get("content-type") || "application/octet-stream",
      });
      const processed = await processMediaAssets({ files: [file] });
      if (!processed[0])
        throw new Error("This browser could not import " + record.name);
      const asset = await editor.media.addMediaAsset({
        projectId: id,
        asset: processed[0],
      });
      if (!asset)
        throw new Error(
          "Could not save " + record.name + " to browser storage.",
        );
      assets.set(key, asset);
    }
    const scene = project.scenes[0];
    const canvas =
      seed.settings.video_aspect === "16:9"
        ? { width: 1920, height: 1080 }
        : seed.settings.video_aspect === "1:1"
          ? { width: 1080, height: 1080 }
          : { width: 1080, height: 1920 };
    project.settings = {
      ...project.settings,
      canvasSize: canvas,
      canvasSizeMode: "preset",
      fps: { numerator: 30, denominator: 1 },
    };
    scene.tracks.main.elements = seed.scenes
      .filter((s: any) => s.start < seed.duration)
      .map((s: any) => {
        const asset = assets.get(s.asset);
        const length = Math.min(s.duration, seed.duration - s.start);
        return {
          ...element("video", asset, s.start, length),
          name: s.label,
          mptSceneId: s.id,
          isSourceAudioEnabled: false,
          sourceDuration: time({ seconds: asset.duration || length }),
          trimEnd: time({
            seconds: Math.max(0, (asset.duration || length) - length),
          }),
        };
      });
    scene.tracks.audio = seed.audio.map((s: any) => {
      const asset = assets.get(s.asset);
      const item: any = element("audio", asset, s.start, s.duration);
      item.trimStart = time({ seconds: s.in });
      item.trimEnd = time({
        seconds: Math.max(
          0,
          (asset.duration || s.duration) - s.in - s.duration,
        ),
      });
      item.sourceDuration = time({ seconds: asset.duration || s.duration });
      item.params = {
        ...item.params,
        volume: s.gain > 0 ? 20 * Math.log10(s.gain) : -60,
        muted: s.muted || s.gain === 0,
      };
      return {
        id: crypto.randomUUID(),
        name: s.name,
        type: "audio",
        muted: false,
        elements: [item],
      };
    });
    if (seed.captions.length) {
      const track = {
        id: crypto.randomUUID(),
        name: "Captions",
        type: "text",
        hidden: false,
        elements: seed.captions.map((cue: any) => {
          const style = {
            ...seed.settings,
            ...seed.caption_style,
            ...cue.style,
          };
          const percent =
            style.subtitle_position === "top"
              ? 15
              : style.subtitle_position === "center"
                ? 50
                : style.subtitle_position === "custom"
                  ? style.custom_position
                  : 85;
          const text: any = buildTextElement({
            raw: {},
            startTime: time({ seconds: cue.start_ms / 1000 }),
          });
          return {
            ...text,
            id: crypto.randomUUID(),
            name: cue.text,
            duration: time({ seconds: (cue.end_ms - cue.start_ms) / 1000 }),
            params: {
              ...text.params,
              content: cue.text,
              fontSize:
                ((style.font_size || 60) * FONT_SIZE_SCALE_REFERENCE) /
                canvas.height,
              fontFamily: importedFont(style.font_name),
              color: style.text_fore_color || "#FFFFFF",
              "transform.positionY": canvas.height * (percent / 100 - 0.5),
              "background.enabled": !!style.text_background_color,
              "background.color": style.text_background_color || "#000000",
            },
          };
        }),
      };
      scene.tracks.overlay = [track];
    }
    project.metadata.duration = time({ seconds: seed.duration });
    await storageService.saveProject({ project });
    await editor.project.loadProject({ id });
    await persist(project);
    if (seed.notes.length)
      toast.info("Project import notes", {
        description: seed.notes.join(" "),
        duration: 15000,
      });
  }
  // Upgrade old drafts by matching immutable source hashes, never clip position.
  const clips = await (await api("clips")).json();
  const assets =
    data.mode === "restore"
      ? data.media
      : [...known].map(([id, blob]) => ({ id, blob }));
  for (const scene of project.scenes) {
    for (const track of [scene.tracks.main, ...scene.tracks.overlay]) {
      for (const item of track.elements) {
        if (item.type !== "video") continue;
        const digest = assets.find((a: any) => a.id === item.mediaId)?.blob;
        const matches = clips.scenes.filter((s: any) =>
          s.versions.some((v: any) => v.id === digest),
        );
        if (
          matches.length === 1 &&
          (!item.mptSceneId || item.mptSceneId === matches[0].id)
        ) {
          item.mptSceneId = matches[0].id;
          item.mptVersionId ||= digest;
        }
      }
    }
  }
  const families = project.scenes.flatMap((s: any) =>
    s.tracks.overlay.flatMap((t: any) =>
      t.elements
        .filter((e: any) => e.type === "text")
        .map((e: any) => e.params.fontFamily),
    ),
  );
  await loadFonts({ families });
  await storageService.saveProject({ project });
  const query = new URLSearchParams(window.location.search);
  query.set("project", project.metadata.id);
  window.history.replaceState(
    null,
    "",
    window.location.pathname + "?" + query.toString(),
  );
  const original = storageService.saveProject.bind(storageService);
  storageService.saveProject = async (args: any) => {
    await original(args);
    if (ready) await schedule(args.project);
  };
  // OpenCut's native export is retained. Also save successful exports to the task.
  const originalExport = editor.project.export.bind(editor.project);
  editor.project.export = async (args: any) => {
    await loadFonts({
      families: editor.scenes
        .getScenes()
        .flatMap((s: any) =>
          s.tracks.overlay.flatMap((t: any) =>
            t.elements
              .filter((e: any) => e.type === "text")
              .map((e: any) => e.params.fontFamily),
          ),
        ),
    });
    const result = await originalExport(args);
    if (result.success && result.buffer) {
      try {
        await api("export/" + args.options.format, {
          method: "POST",
          body: result.buffer,
        });
        toast.success("Export saved to the MoneyPrinter task");
      } catch (error: any) {
        toast.error("Video download is ready. Saving to the task failed.", {
          description: error.message,
        });
      }
    }
    return result;
  };
  ready = true;
  setStatus("Saved to this task");
  return project.metadata.id;
}

export async function downloadBackup() {
  await saveNow();
  const response = await api("archive");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "editable-project.mptproject.zip";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
