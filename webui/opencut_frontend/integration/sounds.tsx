import { Button } from "@/components/ui/button";
import { useAssetsPanelStore } from "@/components/editor/panels/assets/assets-panel-store";
export function SoundsView() {
  const setActiveTab = useAssetsPanelStore((state) => state.setActiveTab);
  return (
    <div className="space-y-4 p-5 text-sm">
      <h2>Music and sound effects</h2>
      <p className="text-muted-foreground">
        Your saved audio tracks are already on the timeline. Import more
        recordings or music files from the Media panel.
      </p>
      <Button onClick={() => setActiveTab("media")}>Open media library</Button>
      <p className="text-muted-foreground text-xs">
        OpenCut’s hosted sound search is not connected in this local
        installation.
      </p>
    </div>
  );
}
