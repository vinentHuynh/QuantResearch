import { useState } from 'react';
import { Button, Checkbox, Group, Modal, ScrollArea, Stack } from '@mantine/core';
import { IconMinus } from '@tabler/icons-react';
import type { CollectiveItem } from '../../../shared/ts/portfolio.ts';
import { strategyTitle } from '../../../shared/ts/formatting.ts';

export function PortfolioStrategyRemoval({ selected, onRemove }: {
  selected: CollectiveItem[];
  onRemove: (ids: string[]) => void;
}) {
  const [checkedIds, setCheckedIds] = useState<string[] | null>(null);
  const checked = selected.filter((item) => checkedIds?.includes(item.id)).map((item) => item.id);
  const allChecked = checked.length > 0 && checked.length === selected.length;
  const close = () => setCheckedIds(null);

  return (
    <>
      {selected.length > 0 && (
        <Button variant='default' size='xs' leftSection={<IconMinus size={14} />} aria-haspopup='dialog' onClick={() => setCheckedIds([])}>
          Remove strategies
        </Button>
      )}
      <Modal opened={checkedIds !== null} onClose={close} title='Remove strategies' centered>
        <Stack gap='md'>
          {selected.length > 1 && (
            <Checkbox
              label='Select all'
              checked={allChecked}
              indeterminate={checked.length > 0 && !allChecked}
              onChange={(event) => setCheckedIds(event.currentTarget.checked ? selected.map((item) => item.id) : [])}
            />
          )}
          <Checkbox.Group aria-label='Strategies to remove' value={checked} onChange={setCheckedIds}>
            <ScrollArea.Autosize mah='45dvh' offsetScrollbars>
              <Stack gap='sm' px={2} py={2}>
                {selected.map((item) => (
                  <Checkbox
                    key={item.id}
                    value={item.id}
                    label={strategyTitle(item.name)}
                    description={`${item.symbol} · ${item.timeframe} · ${item.start} – ${item.end}`}
                  />
                ))}
              </Stack>
            </ScrollArea.Autosize>
          </Checkbox.Group>
          <Group justify='flex-end' gap='xs'>
            <Button variant='default' onClick={close}>Cancel</Button>
            <Button color='red' disabled={!checked.length} onClick={() => { onRemove(checked); close(); }}>
              {checked.length ? `Remove ${checked.length} ${checked.length === 1 ? 'strategy' : 'strategies'}` : 'Remove'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
