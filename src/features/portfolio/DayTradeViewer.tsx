import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Table,
  Text,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import type { CollectiveItem, GateReplay } from "../../../shared/ts/portfolio";
import type { DayChart } from "../../../shared/ts/tradeChart";
import { workbenchRequest } from "../../shared/api/workbench";
import { formatMoney } from "./collectiveViewModel";
import { TradeCandles } from "./TradeCandles";
import "./tradeChart.css";

const fmt = (value?: number) =>
  value === undefined
    ? "—"
    : value.toLocaleString("en-US", { maximumFractionDigits: 4 });
function stamp(value: string, day: string) {
  const utc = new Date(value).toISOString();
  return (
    (utc.startsWith(day) ? "" : utc.slice(0, 10) + " ") + utc.slice(11, 19)
  );
}

function ChartBody({
  item,
  day,
  replay,
  copies,
  limits,
  initialFocus,
  onTradeDay,
}: {
  item: CollectiveItem;
  day: string;
  replay: GateReplay;
  copies: number;
  limits: { start: string; end: string };
  initialFocus?: number;
  onTradeDay: (day: string, index: number) => void;
}) {
  const [data, setData] = useState<DayChart | null>(null);
  const [error, setError] = useState("");
  const [attempt, retry] = useState(0);
  const [focus, setFocus] = useState(initialFocus);
  const [focusRevision, setFocusRevision] = useState(0);
  const [dates, setDates] = useState(day);
  const [adjacent, setAdjacent] = useState<DayChart[]>([]);
  const [adjacentStatus, setAdjacentStatus] = useState("");
  const cache = useRef(new Map<string, DayChart>());
  function selectTrade(index: number) {
    setFocus(index);
    setFocusRevision((n) => n + 1);
  }
  useEffect(() => {
    const controller = new AbortController();
    const days = dates.split(",").filter((date) => date !== day);
    const missing = days.filter((date) => !cache.current.has(date));
    const display = () =>
      setAdjacent(days.flatMap((date) => cache.current.get(date) ?? []));
    display();
    setAdjacentStatus(missing.length ? "Loading adjoining candles…" : "");
    Promise.all(
      missing.map(async (date) => {
        const value = await workbenchRequest<DayChart>(
          "/collective/chart",
          { id: item.id, checksum: item.checksum, day: date },
          "POST",
          controller.signal,
        );
        if (!controller.signal.aborted) {
          cache.current.set(date, value);
          if (cache.current.size > 8)
            cache.current.delete(cache.current.keys().next().value!);
        }
      }),
    )
      .then(() => {
        if (!controller.signal.aborted) {
          display();
          setAdjacentStatus(
            days
              .flatMap((date) => cache.current.get(date)?.notes ?? [])
              .join(" "),
          );
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setAdjacentStatus(reason.message);
      });
    return () => controller.abort();
  }, [dates, day, item.id, item.checksum]);
  useEffect(() => {
    const controller = new AbortController();
    workbenchRequest<DayChart>(
      "/collective/chart",
      { id: item.id, checksum: item.checksum, day },
      "POST",
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, [item.id, item.checksum, day, attempt]);
  if (error)
    return (
      <Alert color="red" title="Chart unavailable">
        {error}
        <Button
          ml="sm"
          size="compact-sm"
          variant="default"
          onClick={() => {
            setError("");
            retry((n) => n + 1);
          }}
        >
          Retry
        </Button>
      </Alert>
    );
  if (!data)
    return (
      <Group role="status" py="xl" justify="center">
        <Loader size="sm" />
        Loading candles and trades…
      </Group>
    );
  const trades = data.trades.filter((t) => replay.accepted.has(t.index));
  const focused = trades.find((t) => t.index === focus) ?? trades[0];
  const slices = [data, ...adjacent];
  const candles = slices
    .flatMap((slice) => slice.candles)
    .sort((a, b) => a.time - b.time);
  const chartTrades = [
    ...new Map(
      [...adjacent, data]
        .flatMap((slice) => slice.trades)
        .filter((t) => replay.accepted.has(t.index))
        .map((t) => [t.index, t]),
    ).values(),
  ];
  function focusFill(index: number, timestamp: string) {
    const fillDay = new Date(timestamp).toISOString().slice(0, 10);
    if (fillDay === day) selectTrade(index);
    else onTradeDay(fillDay, index);
  }
  function fillTime(timestamp: string, index: number) {
    const fillDay = new Date(timestamp).toISOString().slice(0, 10);
    const label = stamp(timestamp, day);
    if (fillDay === day || fillDay < limits.start || fillDay > limits.end)
      return <small>{label}</small>;
    return (
      <small>
        <button
          className="trade-focus"
          onClick={() => focusFill(index, timestamp)}
        >
          {label}
        </button>
      </small>
    );
  }
  const closed = trades.filter((t) =>
    new Date(t.exit).toISOString().startsWith(day),
  ).length;
  return (
    <>
      <TradeCandles
        day={day}
        candles={candles}
        trades={chartTrades}
        focused={focused}
        focusRevision={focusRevision}
        onFocus={focusFill}
        limits={limits}
        onDates={setDates}
      />
      {adjacentStatus && (
        <Text size="xs" c="dimmed" role="status" mt="xs">
          {adjacentStatus}
        </Text>
      )}
      {data.reference && (
        <Text size="xs" c="dimmed" mt="xs">
          Reference candles from the registered {item.symbol} dataset. This
          history has no linked candle version.
        </Text>
      )}
      {data.notes.map((note) => (
        <Text size="sm" key={note} mt="xs">
          {note}
        </Text>
      ))}
      <Group justify="space-between" mt="lg" mb="xs">
        <Text fw={650}>Trades · {day}</Text>
        <Text size="sm" c="dimmed">
          {closed} closed · {trades.length - closed} carried forward
        </Text>
      </Group>
      {!trades.length ? (
        <Text size="sm" c="dimmed">
          No portfolio trades were open on this day for this strategy.
        </Text>
      ) : (
        <div className="trade-list">
          <Table withRowBorders>
            <Table.Thead>
              <Table.Tr>
                {[
                  "Trade",
                  "Entry (UTC)",
                  "Exit (UTC)",
                  "Initial stop",
                  "Initial target",
                  "Trade net P&L",
                ].map((v) => (
                  <Table.Th key={v}>{v}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {trades.map((trade, i) => {
                const size = copies * (replay.weights.get(trade.index) ?? 1);
                const qty =
                  trade.quantity === undefined
                    ? undefined
                    : trade.quantity * size;
                return (
                  <Table.Tr key={trade.index} data-focused={focused === trade}>
                    <Table.Td>
                      <button
                        className="trade-focus"
                        aria-label={`Focus trade ${i + 1}`}
                        aria-pressed={focused === trade}
                        onClick={() => selectTrade(trade.index)}
                      >
                        #{i + 1} {trade.side ?? "Trade"}
                      </button>
                      {qty !== undefined && (
                        <small>
                          {fmt(qty)} {qty === 1 ? "contract" : "contracts"}
                        </small>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <b>{fmt(trade.entryPrice)}</b>
                      {fillTime(trade.entry, trade.index)}
                    </Table.Td>
                    <Table.Td>
                      <b>{fmt(trade.exitPrice)}</b>
                      {fillTime(trade.exit, trade.index)}
                      {trade.exit_reason && <small>{trade.exit_reason}</small>}
                    </Table.Td>
                    <Table.Td>{fmt(trade.stop)}</Table.Td>
                    <Table.Td>{fmt(trade.target)}</Table.Td>
                    <Table.Td>{formatMoney(trade.pnl * size)}</Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </div>
      )}
      {trades.some(
        (t) =>
          t.stop === undefined ||
          t.target === undefined ||
          t.entryPrice === undefined ||
          t.exitPrice === undefined,
      ) && (
        <Text size="xs" c="dimmed" mt="xs">
          A dash means the price was unavailable in the saved ledger. Fills with
          only a timestamp appear along the top of the chart.
        </Text>
      )}
    </>
  );
}

export function DayTradeViewer({
  day,
  items,
  initialId,
  replays,
  copies,
  onClose,
  previous,
  next,
  onDay,
  limits,
}: {
  day: string;
  items: CollectiveItem[];
  initialId: string;
  replays: Map<string, GateReplay>;
  copies: Record<string, number>;
  onClose: () => void;
  previous?: string;
  next?: string;
  onDay: (day: string) => void;
  limits: { start: string; end: string };
}) {
  const [chosen, setChosen] = useState(initialId);
  const [requestedTrade, setRequestedTrade] = useState<{
    day: string;
    id: string;
    index: number;
  }>();
  const item = items.find((i) => i.id === chosen) ?? items[0];
  const small = useMediaQuery("(max-width: 700px)");
  return (
    <Modal
      opened
      onClose={onClose}
      fullScreen={small}
      size="min(1120px, 96vw)"
      centered
      title={
        <Text fw={650} size="lg">
          Day trade chart
        </Text>
      }
      className="day-trade-viewer"
    >
      <Group justify="space-between" align="center" mb="md" gap="sm">
        {items.length > 1 ? (
          <Select
            aria-label="Chart strategy"
            value={item.id}
            allowDeselect={false}
            onChange={(v) => v && setChosen(v)}
            data={items.map((i) => ({
              value: i.id,
              label: i.symbol + " · " + i.name + " · " + i.timeframe,
            }))}
          />
        ) : (
          <Text fw={600}>
            {item.symbol} · {item.name} · {item.timeframe}
          </Text>
        )}
        <Group gap="xs" wrap="nowrap">
          <Button
            size="compact-sm"
            variant="default"
            aria-label="Previous chart day"
            disabled={!previous}
            onClick={() => previous && onDay(previous)}
          >
            ‹
          </Button>
          <Text size="sm" fw={600}>
            {day} UTC
          </Text>
          <Button
            size="compact-sm"
            variant="default"
            aria-label="Next chart day"
            disabled={!next}
            onClick={() => next && onDay(next)}
          >
            ›
          </Button>
        </Group>
      </Group>
      <ChartBody
        key={[day, item.id, item.checksum].join("/")}
        item={item}
        day={day}
        replay={replays.get(item.id)!}
        copies={copies[item.id]}
        limits={limits}
        initialFocus={
          requestedTrade?.day === day && requestedTrade.id === item.id
            ? requestedTrade.index
            : undefined
        }
        onTradeDay={(value, index) => {
          setRequestedTrade({ day: value, id: item.id, index });
          onDay(value);
        }}
      />
    </Modal>
  );
}
