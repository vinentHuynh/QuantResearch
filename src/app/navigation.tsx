import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  IconCode,
  IconDatabase,
  IconLayersIntersect,
  IconRoute,
} from "@tabler/icons-react";

export type Page =
  | "workspace"
  | "portfolio"
  | "scorecards"
  | "runs"
  | "new-run"
  | "evaluations"
  | "event-studies"
  | "watchlist"
  | "scripts"
  | "datasets";
export type Route = { page: Page; sub: string };

const defaults: Record<Page, string> = {
  workspace: "",
  portfolio: "overview",
  scorecards: "",
  runs: "all",
  "new-run": "",
  evaluations: "",
  "event-studies": "",
  watchlist: "",
  scripts: "runnable",
  datasets: "",
};

export function parseRoute(hash: string): Route {
  if (hash === "#/watchlist" || hash === "#watchlist")
    return { page: "workspace", sub: "" };
  // Links shared before the redesign keep working.
  if (hash === "#collective-strategies")
    return { page: "portfolio", sub: "strategies" };
  if (hash === "#collective-calendar")
    return { page: "portfolio", sub: "calendar" };
  const [page, sub] = hash.replace(/^#\/?/, "").split("/");
  if (page && page in defaults)
    return { page: page as Page, sub: sub || defaults[page as Page] };
  return { page: "portfolio", sub: "overview" };
}
export const href = (page: Page, sub?: string) =>
  `#/${page}${sub && sub !== defaults[page] ? `/${sub}` : ""}`;

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    if (["#/watchlist", "#watchlist"].includes(window.location.hash))
      window.history.replaceState(null, "", href("workspace"));
    const sync = () => {
      if (["#/watchlist", "#watchlist"].includes(window.location.hash))
        window.history.replaceState(null, "", href("workspace"));
      setRoute(parseRoute(window.location.hash));
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const go = useCallback((page: Page, sub?: string) => {
    const target = href(page, sub);
    if (window.location.hash === target)
      setRoute(parseRoute(target));
    else window.location.hash = target;
  }, []);
  return [route, go] as const;
}

export type NavItem = {
  page: Page;
  label: string;
  icon: ReactNode;
  count?: number;
};

export function navGroups(counts: Partial<Record<Page, number>>) {
  const item = (page: Page, label: string, icon: ReactNode): NavItem => ({
    page,
    label,
    icon,
    count: counts[page],
  });
  return [
    {
      label: "Main",
      items: [
        item("portfolio", "Combined portfolio", <IconLayersIntersect size={16} />),
        item("workspace", "Research", <IconRoute size={16} />),
        item("scripts", "Scripts & library", <IconCode size={16} />),
      ],
    },
    {
      label: "Tools",
      items: [
        item("datasets", "Datasets", <IconDatabase size={16} />),
      ],
    },
  ];
}

