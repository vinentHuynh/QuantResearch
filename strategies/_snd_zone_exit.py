"""Zone exit decisions from information available by the signal bar close."""
from strategies._snd_model import SND


class SNDZoneExit(SND):
    def __init__(self, bars, parameters, request):
        super().__init__(bars, parameters, request)
        self.zone_exit = parameters['zone_exit']

    def on_close(self, i, bar, state):
        # These zones existed at the bar open. Newly activated zones use only
        # completed higher-timeframe candles and are also known at that open.
        # Mirror the source's per-side zone capacity, including new arrivals.
        new = [z for z in self.events.get(i, ())
               if (z.direction == 'short') == (state['position'] > 0)]
        old = self.shorts if state['position'] > 0 else self.longs
        opposing = (list(reversed(new)) + list(old))[:self.args.max_zones]
        order = super().on_close(i, bar, state)
        # Existing bracket exits already happened intrabar. Scheduled close
        # takes priority over a zone signal that would fill next minute.
        if self.zone_exit == 'baseline' or not state['position'] or order is not None:
            return order
        for zone in opposing:
            if self.zone_exit == 'close-inside':
                hit = min(zone.proximal, zone.distal) <= float(bar.close) <= max(zone.proximal, zone.distal)
            else:
                hit = float(bar.high) >= zone.proximal if state['position'] > 0 else float(bar.low) <= zone.proximal
            if hit:
                return {'target': 0, 'timing': 'next-open',
                        'reason': 'snd-opposing-zone-' + self.zone_exit}
        return order
