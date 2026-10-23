import pytest


@pytest.fixture(autouse=True)
def isolate_optional_model(monkeypatch):
    """Unit tests opt into stand-ins; live model evaluation is an explicit CLI run."""
    monkeypatch.delenv('QUESTION_BANK_MODEL_PATH', raising=False)
