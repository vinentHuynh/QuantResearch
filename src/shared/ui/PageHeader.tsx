import type { ReactNode } from "react";

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
