import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type {
  CollectiveCatalog,
  CollectiveSeries,
} from "../../../shared/ts/portfolio.ts";

export function useCollectiveSeries(
  catalog: CollectiveCatalog | null,
  ids: string,
  setError: Dispatch<SetStateAction<string>>,
) {
  const [histories, setHistories] = useState<CollectiveSeries[]>([]);
  const [seriesCatalog, setSeriesCatalog] = useState<CollectiveCatalog | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    if (!catalog || !ids) {
      setLoading(false);
      return () => controller.abort();
    }
    let retry: number | undefined;
    const load = async () => {
      // Keep the last verified histories visible until their replacements load.
      setLoading(true);
      let canRetry = true;
      try {
        const response = await fetch("/api/workbench/collective/series", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: ids.split(",") }),
          signal: controller.signal,
        });
        canRetry = response.ok || response.status >= 500;
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (controller.signal.aborted) return;
        setHistories(data as CollectiveSeries[]);
        setSeriesCatalog(catalog);
        setError("");
      } catch (error) {
        if (controller.signal.aborted) return;
        setError(String(error));
        if (canRetry) retry = window.setTimeout(load, 5000);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(retry);
    };
  }, [catalog, ids, setError]);

  return { histories, seriesCatalog, loading, setLoading };
}
