"""Current aggregate dispatch policy; retained finite-session policies are separate.

Keep attempt declarations, schedule slots, quota reservations and transport bounds
on this immutable policy. Reading it does not access credentials or owner state.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class AggregatePolicy:
    version: str = 'predict-daytime-odds-3'
    endpoint: str = 'https://api.the-odds-api.com'
    bookmakers: tuple[str, ...] = ('novig', 'prophetx', 'pinnacle')
    markets: tuple[str, ...] = ('h2h', 'spreads', 'totals')
    interval_seconds: int = 900
    timezone: str = 'America/New_York'
    opens_at_hour: int = 9
    closes_at_hour: int = 23
    requests_per_cycle: int = 7
    bootstrap_requests: int = 1
    shared_batches_per_cycle: int = 6
    credits_per_batch: int = 3
    monthly_ceiling: int = 100000
    engineering_reserve: int = 50
    response_bytes: int = 2 * 1024 * 1024
    cycle_bytes: int = 16 * 1024 * 1024
    timeout_seconds: int = 20
    retries: int = 0
    inventory_seconds: int = 21600

    @property
    def worst_case_credits_per_cycle(self):
        return self.shared_batches_per_cycle * self.credits_per_batch

    def record(self, sports):
        """Return a detached declaration with the existing attempt schema."""
        return dict(version=self.version, requests_per_cycle=self.requests_per_cycle,
            bootstrap_requests=self.bootstrap_requests,
            shared_batches_per_cycle=self.shared_batches_per_cycle,
            worst_case_credits_per_cycle=self.worst_case_credits_per_cycle,
            monthly_ceiling=self.monthly_ceiling, engineering_reserve=self.engineering_reserve,
            response_bytes=self.response_bytes, cycle_bytes=self.cycle_bytes,
            timeout_seconds=self.timeout_seconds, retries=self.retries,
            endpoint=self.endpoint+'/v4/sports', bookmakers=list(self.bookmakers),
            markets=list(self.markets), interval_seconds=self.interval_seconds,
            window=f'{self.opens_at_hour:02}:00 inclusive to {self.closes_at_hour:02}:00 exclusive {self.timezone}',
            scope=list(sports))


POLICY = AggregatePolicy()
