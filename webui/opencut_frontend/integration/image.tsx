import React from "react";
export default function Image({
  src,
  fill,
  priority,
  unoptimized,
  quality,
  loader,
  style,
  ...props
}: any) {
  return (
    <img
      style={
        fill
          ? {
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              ...style,
            }
          : style
      }
      src={typeof src === "string" ? src : src?.src}
      {...props}
    />
  );
}
