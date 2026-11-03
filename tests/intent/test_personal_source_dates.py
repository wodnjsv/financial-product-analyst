from datetime import date

import pytest

from financial_agent.intent.personal_runtime import _source_date_defaults
from financial_agent.intent.view import ActiveDatasetPin


class Engine:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def connect(self):
        return self

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, statement, parameters=None):
        self.statements.append(str(statement))
        return self

    def mappings(self):
        return self

    def all(self):
        return self.rows


def aum(**changes):
    return dict(metric_id='organizer.pref02n001.aum', product_family='overseas_etf',
                first_date=date(2026, 8, 22), last_date=date(2026, 8, 22),
                observation_count=5, dated_count=5, **changes)


@pytest.mark.asyncio
async def test_actual_single_date_is_pinned_and_not_replaced_with_cutoff():
    engine = Engine([aum()])
    pin = ActiveDatasetPin(dataset_version='dataset-v1', manifest_hash='a' * 64)
    defaults = await _source_date_defaults(engine, pin, date(2026, 8, 24))
    assert defaults.manifest_hash == pin.manifest_hash
    assert defaults.defaults[0].as_of_date == date(2026, 8, 22)
    assert engine.statements[0] == 'SET TRANSACTION READ ONLY'


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'last_date': date(2026, 8, 23)}, {'dated_count': 4},
    {'first_date': None}, {'observation_count': 0},
    {'first_date': date(2026, 8, 25), 'last_date': date(2026, 8, 25)},
    {'product_family': 'domestic_etf'}, {'metric_id': 'unregistered'},
])
async def test_mixed_missing_future_or_inapplicable_dates_provide_no_default(changes):
    rows = [aum() | changes]
    defaults = await _source_date_defaults(
        Engine(rows), ActiveDatasetPin(dataset_version='dataset-v1', manifest_hash='a' * 64),
        date(2026, 8, 24),
    )
    assert defaults.defaults == ()
