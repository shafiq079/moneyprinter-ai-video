import { PreviewPanel as NativePreview } from "../upstream/apps/web/src/preview/components/index";
import { Button } from "@/components/ui/button";
import { useCandidatePreview, setCandidatePreview } from "./clip-preview";
export function PreviewPanel(
  props: React.ComponentProps<typeof NativePreview>,
) {
  const preview = useCandidatePreview();
  return (
    <div className="relative h-full min-h-0">
      <NativePreview {...props} />
      {preview && (
        <div
          className="absolute inset-0 z-40 flex flex-col rounded-sm border bg-background"
          aria-label="Candidate preview"
        >
          <div className="flex items-center justify-between gap-2 border-b p-2 text-sm">
            <span className="truncate">Preview · {preview.name}</span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setCandidatePreview(null)}
            >
              Back to timeline
            </Button>
          </div>
          <video
            key={preview.url}
            src={preview.url}
            controls
            autoPlay
            muted
            className="min-h-0 flex-1 object-contain"
          />
          <p className="text-muted-foreground p-2 text-center text-xs">
            Candidate footage only. Use this version to update the selected
            clip.
          </p>
        </div>
      )}
    </div>
  );
}
