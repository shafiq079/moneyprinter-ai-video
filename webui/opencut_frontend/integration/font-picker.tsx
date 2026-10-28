import { useEffect, useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SYSTEM_FONTS } from "@/fonts/system-fonts";
import { localFonts, loadFontAtlas, loadFullFont } from "./fonts";
import { ChevronDown, Check } from "lucide-react";
import { toast } from "sonner";
export function FontPicker({
  defaultValue,
  onValueChange,
  className,
}: {
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [remote, setRemote] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  useEffect(() => {
    if (open)
      loadFontAtlas().then((a) => setRemote(Object.keys(a?.fonts || {})));
    else setSearch("");
  }, [open]);
  const groups = [
    {
      name: "MoneyPrinter fonts",
      fonts: localFonts.map((f) => ({ family: f.family, label: f.label })),
    },
    {
      name: "System fonts",
      fonts: [...SYSTEM_FONTS].map((family) => ({ family, label: family })),
    },
    {
      name: "OpenCut fonts",
      fonts: remote.map((family) => ({ family, label: family })),
    },
  ];
  const label =
    localFonts.find((f) => f.family === defaultValue)?.label ||
    defaultValue ||
    "Select a font";
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label="Font family"
        className={
          "border-border bg-accent flex h-7 w-full items-center justify-between gap-1 rounded-md border px-2.5 text-sm " +
          (className || "")
        }
      >
        <span className="truncate">{label}</span>
        <ChevronDown size={12} />
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" side="left" align="start">
        <div className="p-2">
          <Input
            autoFocus
            aria-label="Search fonts"
            placeholder="Search fonts…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="max-h-72 overflow-y-auto" aria-busy={!!busy}>
          {groups.map((group) => {
            const fonts = group.fonts.filter((f) =>
              f.label.toLowerCase().includes(search.toLowerCase()),
            );
            const visibleFonts =
              group.name === "OpenCut fonts" ? fonts.slice(0, 80) : fonts;
            return fonts.length ? (
              <div key={group.name}>
                <p className="text-muted-foreground px-3 py-2 text-xs">
                  {group.name}
                </p>
                {visibleFonts.map((f) => (
                  <Button
                    key={f.family}
                    variant="ghost"
                    className="w-full justify-between rounded-none px-3"
                    disabled={!!busy}
                    onClick={async () => {
                      setBusy(f.family);
                      try {
                        await loadFullFont({ family: f.family });
                        onValueChange?.(f.family);
                        setOpen(false);
                      } catch (e: any) {
                        toast.error("Could not load font", {
                          description: e.message,
                        });
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    <span className="truncate">
                      {busy === f.family ? "Loading…" : f.label}
                    </span>
                    {f.family === defaultValue && <Check size={14} />}
                  </Button>
                ))}
              </div>
            ) : null;
          })}
          {groups.every(
            (g) =>
              !g.fonts.some((f) =>
                f.label.toLowerCase().includes(search.toLowerCase()),
              ),
          ) && <p className="p-3 text-sm">No matching fonts.</p>}
        </div>
      </PopoverContent>
    </Popover>
  );
}
