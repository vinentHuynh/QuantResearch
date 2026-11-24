import { useState } from "react";
import { Button, Popover, Text, TextInput, UnstyledButton } from "@mantine/core";
import { IconCheck, IconChevronDown, IconRefresh, IconSettings, IconTrash } from "@tabler/icons-react";
import { href } from "../../app/navigation";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";
import { PortfolioPeriodSelector } from "./PortfolioPeriodSelector";

export type PortfolioView = "overview" | "calendar" | "risk";

const dateLabel = (value: string) =>
  value
    ? new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })
    : "—";

function PortfolioSwitcher({ model }: { model: CollectiveDashboardModel }) {
  const [open, setOpen] = useState(false);
  const {
    deleteCombination,
    loadCombination,
    newPortfolioError,
    saveCombination,
    savedBookName,
    savedBooks,
    selected,
    selectedSavedBookId,
    setSavedBookName,
  } = model;
  const current = savedBooks.find((book) => book.id === selectedSavedBookId);
  return (
    <Popover opened={open} onChange={setOpen} position="bottom-start" width={320} shadow="md" withinPortal>
      <Popover.Target>
        <button
          type="button"
          className="wb-portfolio-switch"
          aria-label={`Portfolios: ${current?.name || "Combined portfolio"}`}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <h1>{current?.name || "Combined portfolio"}</h1>
          <IconChevronDown size={18} aria-hidden="true" />
        </button>
      </Popover.Target>
      <Popover.Dropdown className="wb-portfolio-menu" aria-label="Portfolios">
        <div className="wb-portfolio-menu-label">Portfolios</div>
        <UnstyledButton
          className={`wb-portfolio-menu-item${!current ? " active" : ""}`}
          onClick={() => { loadCombination(null); setOpen(false); }}
        >
          <span>Combined portfolio</span>
          <small>{current ? "Working copy" : "Not saved yet"}</small>
          {!current && <IconCheck size={14} />}
        </UnstyledButton>
        {savedBooks.map((book) => (
          <UnstyledButton
            key={book.id}
            className={`wb-portfolio-menu-item${book.id === selectedSavedBookId ? " active" : ""}`}
            onClick={() => { loadCombination(book.id); setOpen(false); }}
          >
            <span>{book.name}</span>
            <small>Saved {new Date(book.saved_at).toLocaleDateString()}</small>
            {book.id === selectedSavedBookId && <IconCheck size={14} />}
          </UnstyledButton>
        ))}
        {!savedBooks.length && (
          <Text size="xs" c="dimmed" px={4} py={6}>
            No saved portfolios yet. Save this one to come back to it or compare later.
          </Text>
        )}
        {current && (
          <Button
            fullWidth
            mt="xs"
            size="xs"
            variant="light"
            disabled={!selected.length}
            onClick={() => saveCombination("update")}
          >
            Save changes to “{current.name}”
          </Button>
        )}
        <form
          className="wb-portfolio-save"
          onSubmit={(event) => {
            event.preventDefault();
            saveCombination("create");
          }}
        >
          <TextInput
            size="xs"
            label="Save as"
            placeholder="e.g. NQ momentum + overnight"
            value={savedBookName}
            error={newPortfolioError || undefined}
            onChange={(event) => setSavedBookName(event.currentTarget.value)}
          />
          <Button
            type="submit"
            size="xs"
            disabled={!selected.length || !savedBookName.trim() || !!newPortfolioError}
          >
            Save
          </Button>
        </form>
        {current && (
          <Button
            fullWidth
            mt="xs"
            size="xs"
            variant="subtle"
            color="red"
            leftSection={<IconTrash size={13} />}
            onClick={() => { deleteCombination(); setOpen(false); }}
          >
            Delete portfolio
          </Button>
        )}
      </Popover.Dropdown>
    </Popover>
  );
}

export function PortfolioHeader({
  model,
  view,
  watchCount,
  onSettings,
}: {
  model: CollectiveDashboardModel;
  view: PortfolioView;
  watchCount: number;
  onSettings: () => void;
}) {
  const { catalog, pnlPeriod, refreshEvidence, refreshing, selected, selectedSavedBookId, setPnlPeriod, settings } = model;
  const updated = catalog
    ? new Date(catalog.generated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : "";
  const tabs: { id: PortfolioView; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "calendar", label: "Calendar" },
    { id: "risk", label: "Risk" },
  ];
  return (
    <header className="wb-page-head with-tabs wb-portfolio-head">
      <div className="wb-page-top">
        <div className="wb-page-title">
          <PortfolioSwitcher model={model} />
          <p className="wb-page-desc">
            <span data-testid="selected-count">
              {selected.length} {selected.length === 1 ? "strategy" : "strategies"}
            </span>
            {" · "}
            ${Math.round(settings.capital).toLocaleString("en-US")} capital · {dateLabel(settings.start)} – {dateLabel(settings.end)}
            {!selectedSavedBookId && selected.length > 0 && <> · <em>Not saved</em></>}
            {updated && (
              <>
                {" · "}
                <button
                  type="button"
                  className="wb-inline-refresh"
                  aria-label="Refresh data"
                  title="Reload the latest verified histories"
                  disabled={refreshing}
                  onClick={() => void refreshEvidence()}
                >
                  <IconRefresh size={13} className={refreshing ? "wb-spin" : undefined} />
                  Updated {updated}
                </button>
              </>
            )}
          </p>
        </div>
        <div className="wb-page-actions">
          <PortfolioPeriodSelector value={pnlPeriod} onChange={setPnlPeriod} />
          <Button variant="default" size="xs" leftSection={<IconSettings size={14} />} onClick={onSettings}>
            Settings
          </Button>
        </div>
      </div>
      <nav className="wb-tabs" aria-label="Portfolio views">
        {tabs.map((tab) => (
          <a
            key={tab.id}
            href={href("portfolio", tab.id)}
            className={view === tab.id ? "active" : ""}
            aria-current={view === tab.id ? "page" : undefined}
          >
            {tab.label}
            {tab.id === "risk" && watchCount > 0 && (
              <span className="wb-tab-alert" aria-label={`${watchCount} ${watchCount === 1 ? "strategy" : "strategies"} to watch`}>
                {watchCount}
              </span>
            )}
          </a>
        ))}
      </nav>
    </header>
  );
}
