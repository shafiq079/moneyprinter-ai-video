import type { ComponentProps } from "react";
import { PropertyParamField as NativeField } from "../upstream/apps/web/src/components/editor/panels/properties/components/property-param-field";
import { SectionField } from "@/components/section";
import { FontPicker } from "./font-picker";
export function PropertyParamField(props: ComponentProps<typeof NativeField>) {
  if (props.param.type !== "font") return <NativeField {...props} />;
  return (
    <SectionField label={props.param.label}>
      <FontPicker
        defaultValue={String(props.value)}
        onValueChange={(family) => {
          props.onPreview(family);
          props.onCommit();
        }}
      />
    </SectionField>
  );
}
