"""Tests for wrapper.py MCP config writers.

Focused on the shape of the JSON written to provider settings files — Gemini
needs "httpUrl", CodeBuddy needs "url", legacy paths still work.
"""

import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wrapper import (  # noqa: E402
    GROK_MCP_TOKEN_ENV,
    _build_provider_launch,
    _write_grok_mcp_toml,
    _write_json_mcp_settings,
)


class JsonMcpSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "settings.json"

    def _read(self):
        return json.loads(self.target.read_text("utf-8"))

    def test_default_http_uses_httpUrl_key(self):
        # Backward compat: no http_key override → "httpUrl" (Gemini-style)
        _write_json_mcp_settings(self.target, "http://127.0.0.1:8200/mcp",
                                 transport="http")
        data = self._read()
        entry = data["mcpServers"]["agentchattr"]
        self.assertEqual(entry["type"], "http")
        self.assertEqual(entry["httpUrl"], "http://127.0.0.1:8200/mcp")
        self.assertNotIn("url", entry)

    def test_http_key_override_writes_url_key(self):
        # CodeBuddy-style: http_key="url" → MCP-standard "url" key
        _write_json_mcp_settings(self.target, "http://127.0.0.1:8200/mcp",
                                 transport="http", http_key="url")
        data = self._read()
        entry = data["mcpServers"]["agentchattr"]
        self.assertEqual(entry["type"], "http")
        self.assertEqual(entry["url"], "http://127.0.0.1:8200/mcp")
        self.assertNotIn("httpUrl", entry)

    def test_sse_transport_always_uses_url(self):
        # SSE doesn't use httpUrl regardless of http_key setting
        _write_json_mcp_settings(self.target, "http://127.0.0.1:8201/sse",
                                 transport="sse")
        data = self._read()
        entry = data["mcpServers"]["agentchattr"]
        self.assertEqual(entry["type"], "sse")
        self.assertEqual(entry["url"], "http://127.0.0.1:8201/sse")

    def test_bearer_token_written_as_authorization_header(self):
        _write_json_mcp_settings(self.target, "http://127.0.0.1:8200/mcp",
                                 transport="http", token="secret-token-123",
                                 http_key="url")
        entry = self._read()["mcpServers"]["agentchattr"]
        self.assertEqual(entry["headers"]["Authorization"], "Bearer secret-token-123")

    def test_existing_servers_preserved(self):
        # Write a pre-existing settings file with an unrelated server
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text(json.dumps({
            "mcpServers": {"some-other-server": {"type": "http", "url": "http://elsewhere"}}
        }))
        _write_json_mcp_settings(self.target, "http://127.0.0.1:8200/mcp",
                                 transport="http", http_key="url")
        data = self._read()
        self.assertIn("some-other-server", data["mcpServers"])
        self.assertIn("agentchattr", data["mcpServers"])


class ExpanduserPathTests(unittest.TestCase):
    """Verify the _build_provider_launch path expansion logic.

    Unit-testing _build_provider_launch directly would require too much
    scaffolding (registry, token, etc.). Instead we verify Path behavior
    matches our expectations — the wrapper code uses Path(...).expanduser()
    at a single well-defined spot.
    """

    def test_tilde_prefix_expands_to_home(self):
        raw = "~/.codebuddy/.mcp.json"
        expanded = Path(raw).expanduser()
        self.assertTrue(expanded.is_absolute())
        # Must no longer contain a literal ~
        self.assertNotIn("~", str(expanded))
        # Sanity: should land under the user's home dir
        self.assertTrue(str(expanded).startswith(str(Path.home())))

    def test_absolute_path_unchanged_by_expanduser(self):
        raw = str(Path("/tmp/literal-abs").resolve())
        expanded = Path(raw).expanduser()
        self.assertEqual(str(expanded), raw)

    def test_relative_path_stays_relative_after_expanduser(self):
        # Relative paths without ~ aren't made absolute by expanduser alone —
        # that's handled by the subsequent `base / target` join in wrapper.py.
        raw = ".qwen/settings.json"
        expanded = Path(raw).expanduser()
        self.assertFalse(expanded.is_absolute())


class GrokTomlMcpSettingsTests(unittest.TestCase):
    """Grok-native TOML writer: merge-only [mcp_servers.agentchattr], env-var auth."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / ".grok" / "config.toml"

    def test_writes_url_enabled_and_bearer_env_var(self):
        url = "http://127.0.0.1:8244/mcp"
        path = _write_grok_mcp_toml(self.target, url)
        text = path.read_text("utf-8")
        payload = tomllib.loads(text)
        server = payload["mcp_servers"]["agentchattr"]
        self.assertEqual(server["url"], url)
        self.assertTrue(server["enabled"])
        self.assertEqual(server["bearer_token_env_var"], GROK_MCP_TOKEN_ENV)
        self.assertNotIn("headers", server)
        self.assertNotIn("Bearer ", text)

    def test_merge_preserves_unrelated_mcp_servers(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text(
            "# keep this comment and the other server\n"
            "[mcp_servers.linear]\n"
            'url = "https://mcp.linear.app/mcp"\n'
            "enabled = true\n",
            "utf-8",
        )
        _write_grok_mcp_toml(self.target, "http://127.0.0.1:8244/mcp")
        text = self.target.read_text("utf-8")
        self.assertIn("keep this comment", text)
        payload = tomllib.loads(text)
        self.assertEqual(
            payload["mcp_servers"]["linear"]["url"],
            "https://mcp.linear.app/mcp",
        )
        self.assertEqual(
            payload["mcp_servers"]["agentchattr"]["url"],
            "http://127.0.0.1:8244/mcp",
        )

    def test_rewrite_replaces_only_agentchattr_block(self):
        _write_grok_mcp_toml(self.target, "http://127.0.0.1:1111/mcp")
        _write_grok_mcp_toml(self.target, "http://127.0.0.1:2222/mcp")
        payload = tomllib.loads(self.target.read_text("utf-8"))
        server = payload["mcp_servers"]["agentchattr"]
        self.assertEqual(server["url"], "http://127.0.0.1:2222/mcp")
        self.assertEqual(server["bearer_token_env_var"], GROK_MCP_TOKEN_ENV)
        self.assertEqual(list(payload["mcp_servers"]), ["agentchattr"])

    def test_spaced_table_header_is_replaced_not_duplicated(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text(
            "[ mcp_servers.agentchattr ]\n"
            'url = "http://127.0.0.1:1111/mcp"\n'
            "enabled = true\n",
            "utf-8",
        )
        _write_grok_mcp_toml(self.target, "http://127.0.0.1:2222/mcp")
        payload = tomllib.loads(self.target.read_text("utf-8"))
        self.assertEqual(
            payload["mcp_servers"]["agentchattr"]["url"],
            "http://127.0.0.1:2222/mcp",
        )
        self.assertEqual(list(payload["mcp_servers"]), ["agentchattr"])

    def test_invalid_existing_toml_is_not_overwritten(self):
        self.target.parent.mkdir(parents=True)
        garbage = "this is not toml [[[\n"
        self.target.write_text(garbage, "utf-8")
        with self.assertRaises(ValueError):
            _write_grok_mcp_toml(self.target, "http://127.0.0.1:2222/mcp")
        self.assertEqual(self.target.read_text("utf-8"), garbage)

    def test_generic_settings_file_toml_is_not_grok_writer(self):
        """A custom settings_file path ending in .toml must stay JSON, not Grok TOML."""
        target = Path(self.tmp.name) / "custom.toml"
        token = "secret-token-not-for-disk-shape"
        _, _, _, settings_path = _build_provider_launch(
            agent="customcli",
            agent_cfg={
                "mcp_inject": "settings_file",
                "mcp_settings_path": str(target),
                "mcp_transport": "http",
                "mcp_http_key": "url",
            },
            instance_name="customcli-1",
            data_dir=Path(self.tmp.name),
            proxy_url=None,
            extra_args=[],
            env={},
            token=token,
            mcp_cfg={"http_port": 8244},
        )
        raw = settings_path.read_text("utf-8")
        data = json.loads(raw)
        self.assertIn("mcpServers", data)
        self.assertNotIn("[mcp_servers.agentchattr]", raw)
        self.assertNotIn("bearer_token_env_var", raw)


if __name__ == "__main__":
    unittest.main()
