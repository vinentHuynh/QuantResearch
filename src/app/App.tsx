import { MantineProvider } from "@mantine/core";
import { Workbench } from "../features/workspace/WorkbenchPage";

export function App() {
  return (
    <MantineProvider
      defaultColorScheme="light"
      theme={{
        primaryColor: "teal",
        primaryShade: 8,
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        headings: {
          fontFamily: "Georgia, ui-serif, serif",
          fontWeight: "600",
        },
        defaultRadius: "xs",
      }}
    >
      <Workbench />
    </MantineProvider>
  );
}
