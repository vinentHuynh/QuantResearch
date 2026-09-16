import { useEffect, useState, type ReactNode } from "react";
import { Drawer, Modal, TextInput, UnstyledButton } from "@mantine/core";
import { useHotkeys } from "@mantine/hooks";
import {
  IconDots,
  IconFlask,
  IconLayersIntersect,
  IconList,
  IconPlus,
  IconSearch,
} from "@tabler/icons-react";
import { href, navGroups, type NavItem, type Page, type Route } from "./navigation";

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
  children,
}: {
  route: Route;
  counts: Partial<Record<Page, number>>;
  onSearch: (query: string) => SearchResult[];
  children: ReactNode;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [query, setQuery] = useState("");
  useHotkeys([["mod+K", () => setSearchOpen(true)]]);
  const groups = navGroups(counts);
  const active = route.page === "new-run" ? "runs" : route.page;
  const results = searchOpen ? onSearch(query).slice(0, 14) : [];
  const close = () => {
    setSearchOpen(false);
    setQuery("");
  };
  const choose = (result: SearchResult) => {
    close();
    result.run();
  };
  // Close the mobile "More" drawer whenever navigation happens.
  useEffect(() => setMoreOpen(false), [route.page, route.sub]);
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
          onClick={() => setSearchOpen(true)}
        >
          <IconSearch size={14} />
          <span>Search</span>
          <kbd>Ctrl K</kbd>
        </button>
        <a href={href("new-run")} className="wb-new-run">
          <IconPlus size={15} />
          New run
        </a>
        <nav className="wb-nav" aria-label="Primary">
          {navList}
        </nav>
        <div className="wb-sidebar-foot">
          <span className="wb-sim-chip">Historical simulation</span>
          <span>Research results are descriptive, not live signals.</span>
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
          onClick={() => setSearchOpen(true)}
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
          href={href("runs")}
          className={active === "runs" && route.page !== "new-run" ? "active" : ""}
        >
          <IconList size={19} />
          Runs
        </a>
        <a href={href("new-run")} className="wb-bottom-new">
          <span>
            <IconPlus size={19} />
          </span>
          New run
        </a>
        <a
          href={href("evaluations")}
          className={active === "evaluations" ? "active" : ""}
        >
          <IconFlask size={19} />
          Evaluate
        </a>
        <button
          type="button"
          className={
            ["scorecards", "watchlist", "scripts", "datasets"].includes(active)
              ? "active"
              : ""
          }
          onClick={() => setMoreOpen(true)}
        >
          <IconDots size={19} />
          More
        </button>
      </nav>
      <Drawer
        opened={moreOpen}
        onClose={() => setMoreOpen(false)}
        position="bottom"
        size="auto"
        title="Workbench"
        styles={{ content: { height: "auto", maxHeight: "92vh", borderRadius: "16px 16px 0 0" } }}
        classNames={{ body: "wb-more-body" }}
      >
        <nav className="wb-nav wb-nav-light" aria-label="All pages">
          {navList}
        </nav>
      </Drawer>
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

export type HeaderTab = {
  label: string;
  count?: number | string;
  active: boolean;
  href?: string;
  onClick?: () => void;
};

export function PageHeader({
  crumb,
  title,
  actions,
  tabs,
  tabsLabel,
  tabsExtra,
}: {
  crumb: string;
  title: string;
  actions?: ReactNode;
  tabs?: HeaderTab[];
  tabsLabel?: string;
  tabsExtra?: ReactNode;
}) {
  return (
    <header className={`wb-page-head${tabs ? " with-tabs" : ""}`}>
      <div className="wb-page-top">
        <div className="wb-page-title">
          <div className="wb-crumb">{crumb}</div>
          <h1>{title}</h1>
        </div>
        {actions && <div className="wb-page-actions">{actions}</div>}
      </div>
      {tabs && (
        <nav className="wb-tabs" aria-label={tabsLabel || `${title} views`}>
          {tabs.map((tab) => {
            const content = (
              <>
                {tab.label}
                {tab.count !== undefined && (
                  <span className="wb-tab-count" aria-hidden="true">
                    {tab.count}
                  </span>
                )}
              </>
            );
            return tab.href ? (
              <a
                key={tab.label}
                href={tab.href}
                className={tab.active ? "active" : ""}
                aria-current={tab.active ? "page" : undefined}
              >
                {content}
              </a>
            ) : (
              <button
                key={tab.label}
                type="button"
                className={tab.active ? "active" : ""}
                aria-pressed={tab.active}
                onClick={tab.onClick}
              >
                {content}
              </button>
            );
          })}
          {tabsExtra}
        </nav>
      )}
    </header>
  );
}
