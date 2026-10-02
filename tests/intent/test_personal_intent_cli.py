from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from financial_agent.intent.errors import ModelInvocationError
from financial_agent.intent.nvidia_config import NvidiaResolverConfig
from financial_agent.intent import personal_runtime
from scripts import resolve_personal_intent as cli


ROOT = Path(__file__).resolve().parents[2]


def test_explicit_key_file_parsing_is_case_insensitive_and_never_sets_env(tmp_path, monkeypatch):
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    monkeypatch.setenv('FINANCIAL_AGENT_INTENT_MODEL_ID', 'z-ai/glm-5.3-flash')
    key_file = tmp_path / 'local-keys.txt'
    key_file.write_text('Another API = unused\nNvidia API = synthetic-local-key\n', encoding='utf-8')
    actual = cli.load_nvidia_config(key_file)
    assert actual.api_key.get_secret_value() == 'synthetic-local-key'
    assert actual.model_id == 'z-ai/glm-5.3-flash'
    assert 'synthetic-local-key' not in repr(actual)
    assert 'NVIDIA_API_KEY' not in os.environ


@pytest.mark.parametrize('text', [
    'Other API = synthetic-key\n', 'Nvidia API =\n',
    'Nvidia API = synthetic-a\nNVIDIA API = synthetic-b\n',
    'Nvidia API = synthetic-key unexpected-word\n',
])
def test_key_file_rejects_missing_or_ambiguous_nvidia_entries(text, tmp_path):
    key_file = tmp_path / 'local-keys.txt'
    key_file.write_text(text, encoding='utf-8')
    with pytest.raises(cli.PersonalIntentCliError, match='API_KEY_FILE_INVALID'):
        cli.load_nvidia_config(key_file)


def test_key_file_errors_do_not_expose_file_path(tmp_path):
    missing = tmp_path / 'private-key-path.txt'
    with pytest.raises(cli.PersonalIntentCliError) as failure:
        cli.load_nvidia_config(missing)
    assert failure.value.code == 'API_KEY_FILE_INVALID'
    assert str(missing) not in str(failure.value)


def test_env_credentials_are_used_when_no_file_is_explicit(monkeypatch):
    monkeypatch.setenv('NVIDIA_API_KEY', 'synthetic-env-key')
    actual = cli.load_nvidia_config(None)
    assert actual.api_key.get_secret_value() == 'synthetic-env-key'


@pytest.mark.parametrize('url', [
    'postgresql+psycopg://localhost/financial_agent_local',
    'postgresql://127.0.0.1/financial_agent_local',
    'postgresql+psycopg://[::1]/financial_agent_local',
])
def test_cli_accepts_only_supported_local_postgresql_targets(url):
    parsed = cli.local_database_url(url)
    assert parsed.drivername == 'postgresql+psycopg'
    assert parsed.database == 'financial_agent_local'


@pytest.mark.parametrize('url', [
    'postgresql+psycopg://remote.example/financial_agent_local',
    'postgresql+psycopg://localhost/financial_agent',
    'postgresql+psycopg://localhost/financial_agent_local?host=remote.example',
    'postgresql+psycopg://localhost/financial_agent_local?options=-c+role%3Dfa_build',
    'postgresql+asyncpg://localhost/financial_agent_local',
    'sqlite:///financial_agent_local', 'not a database URL',
])
def test_cli_rejects_remote_or_overridden_connection_targets(url):
    with pytest.raises(cli.PersonalIntentCliError, match='LOCAL_DATABASE_TARGET_REQUIRED'):
        cli.local_database_url(url)


class FakeEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


def install_fake_cli(monkeypatch, *, failure=None):
    engine = FakeEngine()
    captured = {}

    def create_engine(url, **kwargs):
        captured['engine_url'] = url
        captured['engine_kwargs'] = kwargs
        return engine

    class Result:
        def to_dict(self):
            return {'question': '국내 ETF를 찾아줘', 'execution_performed': False,
                    'routing': [{'product_family': 'domestic_etf', 'route': 'sql'}]}

    class Service:
        async def resolve(self, question, question_id):
            captured['question'] = question
            captured['question_id'] = question_id
            if failure:
                raise failure
            return Result()

    async def factory(root, actual_engine, actual_config):
        assert actual_engine is engine
        captured['root'] = root
        captured['config'] = actual_config
        return Service()

    monkeypatch.setattr(cli, 'create_async_engine', create_engine)
    monkeypatch.setattr(cli, 'create_personal_intent_service', factory)
    monkeypatch.setenv('NVIDIA_API_KEY', 'synthetic-env-key')
    return engine, captured


def test_cli_prints_json_analysis_and_disposes_engine(monkeypatch, capsys):
    engine, captured = install_fake_cli(monkeypatch)
    assert cli.main(['--question', '국내 ETF를 찾아줘', '--question-id', 'q-local']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['execution_performed'] is False
    assert output['routing'][0]['product_family'] == 'domestic_etf'
    assert captured['question_id'] == 'q-local'
    assert captured['root'] == ROOT
    options = captured['engine_kwargs']['connect_args']
    assert options['connect_timeout'] == 5
    assert '-c role=fa_runtime' in options['options']
    assert '-c default_transaction_read_only=on' in options['options']
    assert '-c statement_timeout=5000' in options['options']
    assert '-c timezone=UTC' in options['options']
    assert engine.disposed


@pytest.mark.parametrize(('failure', 'code'), [
    (ModelInvocationError('MODEL_RATE_LIMITED'), 'MODEL_RATE_LIMITED'),
    (RuntimeError('synthetic-env-key provider response hidden reasoning'), 'PERSONAL_INTENT_FAILED'),
])
def test_cli_prints_only_safe_error_codes_and_disposes(monkeypatch, capsys, failure, code):
    engine, _ = install_fake_cli(monkeypatch, failure=failure)
    assert cli.main(['--question', '국내 ETF를 찾아줘']) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {'error': code, 'execution_performed': False}
    assert 'synthetic-env-key' not in captured.out + captured.err
    assert 'provider response' not in captured.out + captured.err
    assert 'Traceback' not in captured.out + captured.err
    assert engine.disposed


def test_cli_rejects_invalid_target_before_opening_engine(monkeypatch, capsys):
    engine, captured = install_fake_cli(monkeypatch)
    assert cli.main(['--question', '질문', '--database-url',
                     'postgresql+psycopg://user:synthetic-password@remote/financial_agent_local']) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)['error'] == 'LOCAL_DATABASE_TARGET_REQUIRED'
    assert 'engine_url' not in captured
    assert 'synthetic-password' not in output.out + output.err
    assert engine.disposed is False


def test_cli_disposes_engine_when_factory_cannot_read_dataset(monkeypatch, capsys):
    engine, _ = install_fake_cli(monkeypatch)

    async def unavailable_factory(*args):
        raise personal_runtime.ResolverCatalogUnavailable()

    monkeypatch.setattr(cli, 'create_personal_intent_service', unavailable_factory)
    assert cli.main(['--question', '국내 ETF를 찾아줘']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'RESOLVER_CATALOG_UNAVAILABLE'
    assert engine.disposed


class QueryResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class PinConnection:
    def __init__(self, row, failure=None):
        self.row = row
        self.failure = failure
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def begin(self):
        return self

    async def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters))
        if self.failure:
            raise self.failure
        return QueryResult(self.row)


class PinEngine:
    def __init__(self, row, failure=None):
        self.connection = PinConnection(row, failure)

    def connect(self):
        return self.connection


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['building', 'validated', 'active'])
async def test_factory_uses_actual_pin_and_nvidia_provenance(monkeypatch, status):
    captured = {}

    def capture_service(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(personal_runtime, 'PersonalIntentService', capture_service)
    engine = PinEngine({'dataset_version': 'personal-2026-08-24-v1', 'status': status,
                        'manifest_hash': 'a' * 64, 'cutoff_date': date(2026, 8, 24)})
    actual_config = NvidiaResolverConfig(api_key=SecretStr('synthetic-env-key'))
    await personal_runtime.create_personal_intent_service(ROOT, engine, actual_config)
    assert captured['pin'].manifest_hash == 'a' * 64
    assert captured['pin'].dataset_version == 'personal-2026-08-24-v1'
    assert captured['cutoff_date'] == date(2026, 8, 24)
    assert captured['model_id'] == 'z-ai/glm-5.3-flash'
    resolver = captured['resolver']
    assert resolver._manifest.adapter_version == 'nvidia-chat-json-proposal-v5'
    assert resolver._semantic_default_registry is None
    assert resolver._dataset_semantic_defaults is None
    assert type(resolver._adapter).__name__ == 'NvidiaStructuredOutputAdapter'
    statements = engine.connection.statements
    assert statements[0][0] == 'SET TRANSACTION READ ONLY'
    assert statements[-1][1] == {'dataset_version': 'personal-2026-08-24-v1'}
    assert not any('INSERT' in statement or 'UPDATE' in statement for statement, _ in statements)


@pytest.mark.asyncio
@pytest.mark.parametrize('row', [
    None,
    {'dataset_version': 'personal-2026-08-24-v1', 'status': 'failed', 'manifest_hash': 'a' * 64, 'cutoff_date': date(2026, 8, 24)},
    {'dataset_version': 'personal-2026-08-24-v1', 'status': 'retired', 'manifest_hash': 'a' * 64, 'cutoff_date': date(2026, 8, 24)},
    {'dataset_version': 'another-dataset', 'status': 'building', 'manifest_hash': 'a' * 64, 'cutoff_date': date(2026, 8, 24)},
    {'dataset_version': 'personal-2026-08-24-v1', 'status': 'building', 'manifest_hash': 'invalid', 'cutoff_date': date(2026, 8, 24)},
    {'dataset_version': 'personal-2026-08-24-v1', 'status': 'building', 'manifest_hash': 'a' * 64, 'cutoff_date': None},
])
async def test_factory_never_fabricates_or_activates_missing_dataset_pins(row):
    with pytest.raises(personal_runtime.ResolverCatalogUnavailable, match='RESOLVER_CATALOG_UNAVAILABLE'):
        await personal_runtime.create_personal_intent_service(
            ROOT, PinEngine(row), NvidiaResolverConfig(api_key=SecretStr('synthetic-env-key')),
        )


@pytest.mark.asyncio
async def test_factory_sanitizes_database_connection_error():
    failure = OperationalError('private-statement', {}, RuntimeError('synthetic-db-password'))
    with pytest.raises(personal_runtime.ResolverCatalogUnavailable) as error:
        await personal_runtime.create_personal_intent_service(
            ROOT, PinEngine(None, failure), NvidiaResolverConfig(api_key=SecretStr('synthetic-env-key')),
        )
    assert 'synthetic-db-password' not in str(error.value)
