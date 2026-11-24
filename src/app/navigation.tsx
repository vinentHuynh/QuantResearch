import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  IconChartPie,
  IconDatabase,
  IconFlask2,
  IconListDetails,
} from "@tabler/icons-react";

/** The four sections of the workbench, plus the backtest form. */
export type SectionPage = "portfolio" | "strategies" | "runs" | "data" | "new-run";
/** Names used before the redesign. Links and calls that still use them
 * resolve to the section that now holds that content. */
export type LegacyPage =
  | "workspace"
  | "scorecards"
  | "evaluations"
  | "event-studies"
  | "watchlist"
  | "scripts"
  | "datasets";
export type Page = SectionPage | LegacyPage;
export type Route = { page: SectionPage; sub: string; detail: string };

const defaults: Record<SectionPage, string> = {
  portfolio: "overview",
  strategies: "list",
  runs: "all",
  data: "market",
  "new-run": "",
};

const legacyHashes: Record<string, string> = {
  "#/watchlist": "#/strategies",
  "#watchlist": "#/strategies",
  "#collective-strategies": "#/portfolio/strategies",
  "#collective-calendar": "#/portfolio/calendar",
};

export function parseRoute(rawHash: string): Route {
  const hash = legacyHashes[rawHash] || rawHash;
  const [page = "", sub = "", ...rest] = hash.replace(/^#\/?/, "").split("/");
  const detail = rest.join("/");
  switch (page) {
    case "workspace":
    case "scorecards":
    case "watchlist":
      return { page: "strategies", sub: "list", detail: "" };
    case "scripts":
      return {
        page: "strategies",
        sub: sub === "library" ? "library" : sub === "archive" ? "archive" : "scripts",
        detail: "",
      };
    case "datasets":
      return { page: "data", sub: "market", detail: "" };
    case "event-studies":
      return { page: "data", sub: "studies", detail: "" };
    case "evaluations":
      return { page: "runs", sub: "evaluations", detail: sub };
    case "portfolio":
      return {
        page: "portfolio",
        sub: sub === "pause" ? "risk" : sub === "contributions" || !sub ? "overview" : sub,
        detail,
      };
  }
  if (page in defaults) {
    const section = page as SectionPage;
    return { page: section, sub: sub || defaults[section], detail };
  }
  return { page: "portfolio", sub: "overview", detail: "" };
}

export function routeHash(route: Route) {
  const showSub = route.detail || (route.sub && route.sub !== defaults[route.page]);
  return `#/${route.page}${showSub ? `/${route.sub}` : ""}${route.detail ? `/${route.detail}` : ""}`;
}

/** A canonical link. Old page names resolve to their new section. */
export const href = (page: Page, sub?: string, detail?: string) =>
  routeHash(parseRoute(`#/${page}${sub ? `/${sub}` : ""}${detail ? `/${detail}` : ""}`));

export const strategyHref = (id: string) => href("strategies", "detail", encodeURIComponent(id));

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const sync = () => {
      const next = parseRoute(window.location.hash);
      const canonical = routeHash(next);
      // Old bookmarks keep working and the address bar shows the new location.
      if (window.location.hash && window.location.hash !== canonical)
        window.history.replaceState(null, "", canonical);
      setRoute(next);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const go = useCallback((page: Page, sub?: string, detail?: string) => {
    const target = href(page, sub, detail);
    if (window.location.hash === target) setRoute(parseRoute(target));
    else window.location.hash = target;
  }, []);
  return [route, go] as const;
}

export type NavItem = {
  page: SectionPage;
  label: string;
  icon: ReactNode;
  count?: number;
};

export function navGroups(counts: Partial<Record<Page, number>>) {
  const item = (page: SectionPage, label: string, icon: ReactNode): NavItem => ({
    page,
    label,
    icon,
    count: counts[page],
  });
  return [
    {
      label: "",
      items: [
        item("portfolio", "Portfolio", <IconChartPie size={17} />),
        item("strategies", "Strategies", <IconFlask2 size={17} />),
        item("runs", "Runs", <IconListDetails size={17} />),
        item("data", "Data", <IconDatabase size={17} />),
      ],
    },
  ];
}
