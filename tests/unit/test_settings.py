"""
Unit tests for config/settings.py (load_config, _load_dotenv).

Tests run without writing real .env files — the .env loading path is patched
or bypassed so existing developer environments are never polluted.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock


# We import the module functions directly.
from config.settings import load_config, _load_dotenv


# ─────────────────────────────────────────
# load_config() — structure & defaults
# ─────────────────────────────────────────

class TestLoadConfigStructure:
    def test_load_config_returns_dict(self):
        with patch("config.settings.Path.exists", return_value=False):
            cfg = load_config()
        assert isinstance(cfg, dict)

    def test_load_config_returns_all_expected_keys(self):
        expected_keys = {
            "anthropic_api_key",
            "gemini_api_key",
            "brave_api_key",
            "mongo_url",
            "ollama_url",
            "stream",
            "default_model",
            "api_host",
            "api_port",
            "web_port",
        }
        with patch("config.settings.Path.exists", return_value=False):
            cfg = load_config()
        assert expected_keys.issubset(set(cfg.keys()))

    def test_load_config_api_port_is_int(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"API_PORT": "9000"}, clear=False):
            cfg = load_config()
        assert isinstance(cfg["api_port"], int)

    def test_load_config_web_port_is_int(self):
        with patch("config.settings.Path.exists", return_value=False):
            cfg = load_config()
        assert isinstance(cfg["web_port"], int)

    def test_load_config_stream_is_bool(self):
        with patch("config.settings.Path.exists", return_value=False):
            cfg = load_config()
        assert isinstance(cfg["stream"], bool)

    def test_load_config_default_model_is_claude(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {}, clear=False):
            # Remove DEFAULT_MODEL if set so we get the hardcoded default
            env = {k: v for k, v in os.environ.items() if k != "DEFAULT_MODEL"}
            with patch.dict(os.environ, env, clear=True):
                cfg = load_config()
        assert cfg["default_model"] == "claude"

    def test_load_config_default_api_port_is_8000(self):
        env = {k: v for k, v in os.environ.items() if k != "API_PORT"}
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg["api_port"] == 8000

    def test_load_config_default_web_port_is_3000(self):
        env = {k: v for k, v in os.environ.items() if k != "WEB_PORT"}
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg["web_port"] == 3000

    def test_load_config_default_mongo_url(self):
        env = {k: v for k, v in os.environ.items() if k != "MONGO_URL"}
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg["mongo_url"] == "mongodb://mongo:27017"

    def test_load_config_default_ollama_url(self):
        env = {k: v for k, v in os.environ.items() if k != "OLLAMA_URL"}
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg["ollama_url"] == "http://ollama:11434"


# ─────────────────────────────────────────
# load_config() — reads from environment variables
# ─────────────────────────────────────────

class TestLoadConfigReadsEnvVars:
    def test_reads_anthropic_api_key_from_env(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-env-test"}, clear=False):
            cfg = load_config()
        assert cfg["anthropic_api_key"] == "sk-env-test"

    def test_reads_gemini_api_key_from_env(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"GEMINI_API_KEY": "genv-key"}, clear=False):
            cfg = load_config()
        assert cfg["gemini_api_key"] == "genv-key"

    def test_reads_brave_api_key_from_env(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"BRAVE_API_KEY": "brave-test"}, clear=False):
            cfg = load_config()
        assert cfg["brave_api_key"] == "brave-test"

    def test_reads_mongo_url_from_env(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"MONGO_URL": "mongodb://custom:27017"}, clear=False):
            cfg = load_config()
        assert cfg["mongo_url"] == "mongodb://custom:27017"

    def test_reads_ollama_url_from_env(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"OLLAMA_URL": "http://myollama:11434"}, clear=False):
            cfg = load_config()
        assert cfg["ollama_url"] == "http://myollama:11434"

    def test_reads_api_port_from_env(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"API_PORT": "9999"}, clear=False):
            cfg = load_config()
        assert cfg["api_port"] == 9999

    def test_reads_web_port_from_env(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"WEB_PORT": "4000"}, clear=False):
            cfg = load_config()
        assert cfg["web_port"] == 4000

    def test_stream_false_when_env_is_false(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"STREAM": "false"}, clear=False):
            cfg = load_config()
        assert cfg["stream"] is False

    def test_stream_true_when_env_is_true(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"STREAM": "true"}, clear=False):
            cfg = load_config()
        assert cfg["stream"] is True

    def test_stream_true_when_env_is_True_mixed_case(self):
        with patch("config.settings.Path.exists", return_value=False), \
             patch.dict(os.environ, {"STREAM": "True"}, clear=False):
            cfg = load_config()
        assert cfg["stream"] is True


# ─────────────────────────────────────────
# _load_dotenv() — does not overwrite existing env vars
# ─────────────────────────────────────────

class TestLoadDotenv:
    def test_dotenv_does_not_overwrite_existing_env_var(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_VAR=from_dotenv\n")

        with patch.dict(os.environ, {"MY_TEST_VAR": "already_set"}, clear=False):
            _load_dotenv(env_file)
            assert os.environ["MY_TEST_VAR"] == "already_set"

    def test_dotenv_sets_missing_env_var(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_NEW_TEST_VAR_XYZ=from_dotenv\n")

        # Make sure the var doesn't exist before we call _load_dotenv
        os.environ.pop("MY_NEW_TEST_VAR_XYZ", None)
        try:
            _load_dotenv(env_file)
            assert os.environ.get("MY_NEW_TEST_VAR_XYZ") == "from_dotenv"
        finally:
            os.environ.pop("MY_NEW_TEST_VAR_XYZ", None)

    def test_dotenv_ignores_comment_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nREAL_VAR_TEST=value\n")
        os.environ.pop("REAL_VAR_TEST", None)
        try:
            _load_dotenv(env_file)
            assert os.environ.get("REAL_VAR_TEST") == "value"
        finally:
            os.environ.pop("REAL_VAR_TEST", None)

    def test_dotenv_ignores_blank_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nBLANK_LINE_VAR=ok\n\n")
        os.environ.pop("BLANK_LINE_VAR", None)
        try:
            _load_dotenv(env_file)
            assert os.environ.get("BLANK_LINE_VAR") == "ok"
        finally:
            os.environ.pop("BLANK_LINE_VAR", None)

    def test_dotenv_strips_quotes_from_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_VAR="quoted_value"\n')
        os.environ.pop("QUOTED_VAR", None)
        try:
            _load_dotenv(env_file)
            assert os.environ.get("QUOTED_VAR") == "quoted_value"
        finally:
            os.environ.pop("QUOTED_VAR", None)

    def test_dotenv_strips_single_quotes_from_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SINGLE_QUOTED_VAR='single_val'\n")
        os.environ.pop("SINGLE_QUOTED_VAR", None)
        try:
            _load_dotenv(env_file)
            assert os.environ.get("SINGLE_QUOTED_VAR") == "single_val"
        finally:
            os.environ.pop("SINGLE_QUOTED_VAR", None)

    def test_load_config_does_not_overwrite_existing_env_vars_from_dotenv(self, tmp_path):
        """Integration-style: load_config() must call _load_dotenv() which
        must not stomp over env vars already set in the process environment."""
        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=from_dotenv_key\n")

        with patch("config.settings.Path.exists", return_value=True), \
             patch("config.settings.Path.__truediv__", return_value=env_file), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "pre_existing_key"}, clear=False):
            cfg = load_config()

        # The env-var-based value (pre_existing_key) must win over the .env file value
        assert cfg["anthropic_api_key"] == "pre_existing_key"
