import { createContext, useContext, type ReactNode } from "react";

export type HeaderTab = {
  label: string;
  count?: number | string;
  active: boolean;
  href?: string;
  onClick?: () => void;
};

/** A top-level section (Strategies, Runs, Data) that hosts several pages.
 * Pages keep rendering their own PageHeader; inside a section it shows the
 * section's title and tabs, and the page's own tabs become a secondary row. */
export type PageSection = {
  title: string;
  description?: ReactNode;
  tabs: HeaderTab[];
  tabsLabel: string;
  actions?: ReactNode;
  /** The page's own tabs repeat the section tabs; leave them out. */
  hidePageTabs?: boolean;
};

const SectionContext = createContext<PageSection | null>(null);

export function PageSectionProvider({ section, children }: { section: PageSection; children: ReactNode }) {
  return <SectionContext.Provider value={section}>{children}</SectionContext.Provider>;
}

function TabList({ tabs, label, className, extra }: { tabs: HeaderTab[]; label: string; className: string; extra?: ReactNode }) {
  return (
    <nav className={className} aria-label={label}>
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
      {extra}
    </nav>
  );
}

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
  const section = useContext(SectionContext);
  if (section) {
    const pageTabs = !section.hidePageTabs && tabs && tabs.length > 1 ? tabs : null;
    return (
      <header className="wb-page-head with-tabs wb-section-head">
        <div className="wb-page-top">
          <div className="wb-page-title">
            <h1>{section.title}</h1>
            {section.description && <p className="wb-page-desc">{section.description}</p>}
          </div>
          {(section.actions || actions) && (
            <div className="wb-page-actions">
              {actions}
              {section.actions}
            </div>
          )}
        </div>
        <TabList tabs={section.tabs} label={section.tabsLabel} className="wb-tabs" />
        {(pageTabs || (tabsExtra && !section.hidePageTabs)) && (
          <TabList
            tabs={pageTabs || []}
            label={tabsLabel || `${title} views`}
            className="wb-subtabs"
            extra={tabsExtra}
          />
        )}
      </header>
    );
  }
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
        <TabList tabs={tabs} label={tabsLabel || `${title} views`} className="wb-tabs" extra={tabsExtra} />
      )}
    </header>
  );
}
