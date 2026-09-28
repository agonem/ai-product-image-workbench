import pytest
from image_service.background import BackgroundError
from image_service.background_config import load_config, private_environment


def test_explicit_file_is_whitelisted_and_not_evaluated(tmp_path, monkeypatch):
    path = tmp_path / "private.env"
    path.write_text(
        'OPENROUTER_API_KEY="test-secret"\nOPENROUTER_MODEL=test/image\n'
        "OPENROUTER_PROVIDER_TAG=test-provider\nVITE_SECRET=never\n",
        encoding="utf-8",
    )
    for name in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_PROVIDER_TAG",
        "VITE_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_ENV_FILE", str(path))
    assert "VITE_SECRET" not in private_environment()
    config = load_config()
    assert config.model == "test/image" and "test-secret" not in repr(config)
    monkeypatch.setenv("OPENROUTER_MODEL", "override/model")
    assert load_config().model == "override/model"


def test_missing_private_file_has_no_path_or_secret_in_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_ENV_FILE", "/missing/private-secret.env")
    with pytest.raises(BackgroundError) as error:
        load_config()
    assert "private-secret" not in str(error.value)
