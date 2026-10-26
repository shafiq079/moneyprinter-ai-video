import React from "react";
export default function Link({ href, children, prefetch, ...props }: any) {
  return (
    <a href={href} {...props}>
      {children}
    </a>
  );
}
