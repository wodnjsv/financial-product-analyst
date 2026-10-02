from types import SimpleNamespace

import pytest

from scripts import search_personal_question as cli
from financial_agent.intent.personal_search import PersonalSearchError


def install(monkeypatch, failure=None):
    captured = {}

    class Engine:
        async def dispose(self):
            captured['disposed'] = True

    def engine(url, **kwargs):
        captured['url'], captured['kwargs'] = url, kwargs
        return Engine()

    async def intent_factory(root, engine, config):
        return object()

    class Search:
        async def search(self, question, question_id, display_limit):
            captured['request'] = (question, question_id, display_limit)
            if failure:
                raise failure
            return SimpleNamespace(text='검증된 합성 검색 결과 1건')

    monkeypatch.setenv('NVIDIA_API_KEY', 'synthetic-key')
    monkeypatch.setattr(cli, 'create_async_engine', engine)
    monkeypatch.setattr(cli, 'create_personal_intent_service', intent_factory)
    monkeypatch.setattr(cli, 'create_personal_search', lambda *args: Search())
    return captured


def test_question_cli_renders_text_and_uses_readonly_runtime(monkeypatch, capsys):
    captured = install(monkeypatch)
    assert cli.main(['--question', '국내 ETF 총보수', '--display-limit', '3']) == 0
    assert capsys.readouterr().out == '검증된 합성 검색 결과 1건\n'
    assert captured['request'] == ('국내 ETF 총보수', 'local-search', 3)
    options = captured['kwargs']['connect_args']['options']
    assert 'role=fa_runtime' in options
    assert 'default_transaction_read_only=on' in options
    assert 'statement_timeout=5000' in options
    assert captured['disposed']


def test_failure_disposes_engine_and_never_prints_exception_payload(monkeypatch, capsys):
    captured = install(monkeypatch, ValueError('secret-bearing-provider-response'))
    assert cli.main(['--question', '합성 질문']) == 1
    output = capsys.readouterr().out
    assert output == '실행 실패: PERSONAL_SEARCH_FAILED\n'
    assert captured['disposed']


def test_remote_database_is_rejected_before_factory(monkeypatch, capsys):
    captured = install(monkeypatch)
    assert cli.main(['--question', '합성 질문', '--database-url',
                     'postgresql://external.example/financial_agent_local']) == 1
    assert capsys.readouterr().out == '실행 실패: LOCAL_DATABASE_TARGET_REQUIRED\n'
    assert 'url' not in captured


@pytest.mark.parametrize('code', ['SQL_RESULT_ROW_LIMIT_EXCEEDED', 'PERSONAL_SQL_TIMEOUT'])
def test_bounded_failure_discloses_narrowing_instruction(monkeypatch, capsys, code):
    install(monkeypatch, PersonalSearchError(code))
    assert cli.main(['--question', '합성 질문']) == 1
    output = capsys.readouterr().out
    assert f'실행 실패: {code}' in output
    assert '범위를 좁혀 주세요' in output
