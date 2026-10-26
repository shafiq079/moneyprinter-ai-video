const router = {
  push: (url: string) =>
    window.location.assign(url.startsWith("/projects") ? "/?view=tasks" : url),
  replace: (url: string) => window.location.replace(url),
};
export function useRouter() {
  return router;
}
export function useParams() {
  return {
    project_id:
      new URLSearchParams(window.location.search).get("project") || "",
  };
}
export function usePathname() {
  return window.location.pathname;
}
export function useSearchParams() {
  return new URLSearchParams(window.location.search);
}
