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
    // Keep the last verified series on screen while an updated catalog's
    // histories load. The selected date window advances only after this fetch.
    setLoading(true);
    fetch("/api/workbench/collective/series", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids.split(",") }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        return data as CollectiveSeries[];
      })
      .then((data) => {
        if (controller.signal.aborted) return;
        setHistories(data);
        setSeriesCatalog(catalog);
        setError("");
        setLoading(false);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setError(String(error));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [catalog, ids, setError]);

  return { histories, seriesCatalog, loading, setLoading };
}
