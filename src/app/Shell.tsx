import { useState, type ReactNode } from "react";
import { Modal, TextInput, UnstyledButton } from "@mantine/core";
import { useHotkeys } from "@mantine/hooks";
import {
  IconFlask,
  IconCode,
  IconLayersIntersect,
  IconRoute,
  IconSearch,
} from "@tabler/icons-react";
import { href, navGroups, type NavItem, type Page, type Route } from "./navigation";
export { PageHeader } from "../shared/ui/PageHeader";
export type { HeaderTab } from "../shared/ui/PageHeader";

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <a
      href={href(item.page)}
      className={`wb-nav-item${active ? " active" : ""}`}
      aria-current={active ? "page" : undefined}
    >
      {item.icon}
      <span>{item.label}</span>
      {item.count !== undefined && (
        <span className="wb-nav-count" aria-hidden="true">
          {item.count.toLocaleString()}
        </span>
      )}
    </a>
  );
}
export type SearchResult = {
  group: string;
  label: string;
  detail?: string;
  run: () => void;
};

export function Shell({
  route,
  counts,
  onSearch,
  onSearchOpen,
  children,
}: {
  route: Route;
  counts: Partial<Record<Page, number>>;
  onSearch: (query: string) => SearchResult[];
  onSearchOpen?: () => void;
  children: ReactNode;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const openSearch = () => {
    setSearchOpen(true);
    onSearchOpen?.();
  };
  useHotkeys([["mod+K", openSearch]]);
  const groups = navGroups(counts);
  const active = ["new-run", "runs", "evaluations", "scorecards", "event-studies", "watchlist"].includes(route.page) ? "workspace" : route.page;
  const results = searchOpen ? onSearch(query).slice(0, 14) : [];
  const close = () => {
    setSearchOpen(false);
    setQuery("");
  };
  const choose = (result: SearchResult) => {
    close();
    result.run();
  };
  const navList = (
    <>
      {groups.map((group) => (
        <div className="wb-nav-group" key={group.label}>
          <div className="wb-nav-label">{group.label}</div>
          {group.items.map((item) => (
            <NavLink key={item.page} item={item} active={active === item.page} />
          ))}
        </div>
      ))}
    </>
  );
  return (
    <div className="wb">
      <aside className="wb-sidebar" aria-label="Workbench">
        <a href={href("portfolio")} className="wb-brand">
          <span className="wb-mark">
            <IconFlask size={18} />
          </span>
          <span>
            <span className="wb-brand-name">Strategy Workbench</span>
            <span className="wb-brand-sub">Local research</span>
          </span>
        </a>
        <button
          type="button"
          className="wb-search"
          onClick={openSearch}
        >
          <IconSearch size={14} />
          <span>Search</span>
          <kbd>Ctrl K</kbd>
        </button>
        <a href={href("workspace")} className="wb-new-run">
          <IconFlask size={15} />
          Research
        </a>
        <nav className="wb-nav" aria-label="Primary">
          {navList}
        </nav>
        <div className="wb-sidebar-foot">
          <span className="wb-sim-chip">Historical simulation</span>
          <span>Historical research</span>
        </div>
      </aside>
      <header className="wb-mobile-bar">
        <a href={href("portfolio")} className="wb-brand">
          <span className="wb-mark">
            <IconFlask size={16} />
          </span>
          <span className="wb-brand-name">Strategy Workbench</span>
        </a>
        <button
          type="button"
          className="wb-icon-button"
          aria-label="Search"
          onClick={openSearch}
        >
          <IconSearch size={19} />
        </button>
      </header>
      <main className="wb-main">{children}</main>
      <nav className="wb-bottom-nav" aria-label="Primary, compact">
        <a
          href={href("portfolio")}
          className={active === "portfolio" ? "active" : ""}
          aria-current={active === "portfolio" ? "page" : undefined}
        >
          <IconLayersIntersect size={19} />
          Portfolio
        </a>
        <a
          href={href("workspace")}
          className={active === "workspace" ? "active" : ""}
        >
          <IconRoute size={19} />
          Research
        </a>
        <a href={href("scripts")} className="wb-bottom-new">
          <span>
            <IconCode size={19} />
          </span>
          Scripts
        </a>
        <a
          href={href("datasets")}
          className={active === "datasets" ? "active" : ""}
        >
          <IconFlask size={19} />
          Data
        </a>
      </nav>
      <Modal
        opened={searchOpen}
        onClose={close}
        title="Search the workbench"
        size="lg"
      >
        <TextInput
          data-autofocus
          aria-label="Search pages, runs, strategies and evaluations"
          placeholder="Pages, runs, strategies, evaluations"
          leftSection={<IconSearch size={15} />}
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && results[0]) choose(results[0]);
          }}
        />
        <div className="wb-search-results">
          {results.map((result, i) => (
            <div key={`${result.group}-${result.label}-${i}`}>
              {(i === 0 || results[i - 1].group !== result.group) && (
                <div className="wb-search-group">{result.group}</div>
              )}
              <UnstyledButton
                className="wb-search-result"
                onClick={() => choose(result)}
              >
                <span>{result.label}</span>
                {result.detail && <small>{result.detail}</small>}
              </UnstyledButton>
            </div>
          ))}
          {!results.length && (
            <p className="wb-search-empty">Nothing matches “{query}”.</p>
          )}
        </div>
      </Modal>
    </div>
  );
}

