"""Username persistence and its precedence order."""

import pytest

from steam_installer import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never read or write the real ~/.config during a test run."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config")
    monkeypatch.delenv(config.ENV_VAR, raising=False)


def test_explicit_username_wins_over_everything(monkeypatch):
    monkeypatch.setenv(config.ENV_VAR, "from_env")
    config.save_username("from_file")
    assert config.resolve_username("explicit", interactive=False) == "explicit"


def test_env_wins_over_the_saved_file(monkeypatch):
    monkeypatch.setenv(config.ENV_VAR, "from_env")
    config.save_username("from_file")
    assert config.resolve_username(None, interactive=False) == "from_env"


def test_a_blank_env_var_does_not_shadow_the_saved_file(monkeypatch):
    monkeypatch.setenv(config.ENV_VAR, "   ")
    config.save_username("from_file")
    assert config.resolve_username(None, interactive=False) == "from_file"


def test_the_saved_file_is_used_when_nothing_else_is_given():
    config.save_username("saved")
    assert config.resolve_username(None, interactive=False) == "saved"


def test_saving_creates_the_directory_and_locks_the_file_down():
    config.save_username("someone")
    assert config.CONFIG_PATH.read_text() == "username=someone\n"
    assert config.CONFIG_PATH.stat().st_mode & 0o777 == 0o600


def test_saving_twice_replaces_rather_than_appends():
    config.save_username("first")
    config.save_username("second")
    assert config.load_username() == "second"


def test_load_returns_none_when_nothing_is_saved():
    assert config.load_username() is None


def test_load_ignores_other_keys_and_malformed_lines():
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_PATH.write_text("# a comment\nnot-a-pair\nother=x\nusername=real\n")
    assert config.load_username() == "real"


def test_an_empty_username_value_reads_as_unset():
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_PATH.write_text("username=\n")
    assert config.load_username() is None


def test_prompting_saves_the_answer(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: " typed ")
    assert config.resolve_username(None, interactive=True) == "typed"
    assert config.load_username() == "typed"


def test_an_empty_answer_is_refused(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "")
    with pytest.raises(config.ConfigError, match="No Steam username entered"):
        config.resolve_username(None, interactive=True)


def test_non_interactive_with_nothing_available_explains_the_options():
    with pytest.raises(config.ConfigError, match="--username"):
        config.resolve_username(None, interactive=False)


def test_a_line_with_no_separator_is_skipped_before_a_valid_one():
    """`partition` returns an empty separator for a bare line; that must not be
    mistaken for a key with an empty value."""
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_PATH.write_text("username\nusername=real\n")
    assert config.load_username() == "real"


def test_a_config_file_with_no_username_key_reads_as_unset():
    config.CONFIG_DIR.mkdir(parents=True)
    config.CONFIG_PATH.write_text("other=x\n# nothing relevant here\n")
    assert config.load_username() is None
