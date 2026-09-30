import { Button, Group } from "@mantine/core";

export function ResearchDownloads({
  id,
  kind,
  names,
}: {
  id: string;
  kind: string;
  names: string[];
}) {
  return (
    <Group gap="xs">
      {names.map((name) => (
        <Button
          key={name}
          component="a"
          size="xs"
          variant="light"
          href={`/api/workbench/research-artifact?kind=${kind}&id=${id}&name=${name}`}
        >
          {name}
        </Button>
      ))}
    </Group>
  );
}
