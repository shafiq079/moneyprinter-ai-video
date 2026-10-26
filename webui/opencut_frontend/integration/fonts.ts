import { api } from "./bridge";
import {
  loadFullFont as upstreamLoad,
  loadFontAtlas,
  getCachedFontAtlas,
  clearFontAtlasCache,
} from "../upstream/apps/web/src/fonts/google-fonts";
import { SYSTEM_FONTS } from "@/fonts/system-fonts";
export { loadFontAtlas, getCachedFontAtlas, clearFontAtlasCache };
export type LocalFont = {
  id: string;
  name: string;
  family: string;
  label: string;
};
export let localFonts: LocalFont[] = [];
const loaded = new Map<string, Promise<void>>();
export async function initFonts() {
  localFonts = await (await api("fonts")).json();
}
export function importedFont(filename: string) {
  return localFonts.find((f) => f.name === filename)?.family || "Arial";
}
export async function loadFullFont(args: {
  family: string;
  weights?: number[];
}) {
  const record = localFonts.find((f) => f.family === args.family);
  if (!record) {
    if (args.family.startsWith("MPT "))
      throw new Error("Install the missing font: " + args.family.slice(4));
    return SYSTEM_FONTS.has(args.family) ? undefined : upstreamLoad(args);
  }
  let promise = loaded.get(record.family);
  if (!promise) {
    promise = (async () => {
      const response = await api("fonts/" + record.id);
      const face = new FontFace(record.family, await response.arrayBuffer());
      await face.load();
      document.fonts.add(face);
    })();
    loaded.set(record.family, promise);
    promise.catch(() => loaded.delete(record.family));
  }
  await promise;
}
export async function loadFonts({ families }: { families: string[] }) {
  await Promise.all(
    [...new Set(families)].map((family) => loadFullFont({ family })),
  );
}
