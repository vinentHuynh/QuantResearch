import { Alert, Button, Code } from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { PageHeader } from "../../shared/ui/PageHeader";
import type { WorkbenchController } from "./useWorkbenchController";

export function WorkbenchAlerts({
  controller,
}: {
  controller: WorkbenchController;
}) {
  const { error, notice, setError, setNotice } = controller;
  if (!error && !notice) return null;
  return (
    <div className="wb-alerts">
      {error && (
        <Alert
          color="red"
          title="Action could not complete"
          withCloseButton
          onClose={() => setError("")}
        >
          {error}
        </Alert>
      )}
      {notice && (
        <Alert color="teal" withCloseButton onClose={() => setNotice("")}>
          {notice}
        </Alert>
      )}
    </div>
  );
}

export function RefreshButton({
  controller,
}: {
  controller: WorkbenchController;
}) {
  return (
    <Button
      variant="default"
      size="xs"
      leftSection={<IconRefresh size={14} />}
      onClick={controller.refreshAll}
    >
      Refresh
    </Button>
  );
}

export function ConnectingPage({
  controller,
}: {
  controller: WorkbenchController;
}) {
  return (
    <>
      <PageHeader crumb="Workbench" title="Connecting…" />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content">
        <div className="wb-card">
          Connecting to the workbench… Start with <Code>npm run dev:full</Code>.
        </div>
      </div>
    </>
  );
}
