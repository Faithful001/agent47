import os
import tempfile
import yaml
import pytest
from unittest.mock import MagicMock, patch

from agent47.infra.git.service import parse_git_diff_to_suggestions
from agent47.agents.graph import setup_sandbox_node

def test_parse_single_line_suggestion():
    diff_text = """diff --git a/src/agent47/domain/auth/service.py b/src/agent47/domain/auth/service.py
index 9d3910c..1b0a887 100644
--- a/src/agent47/domain/auth/service.py
+++ b/src/agent47/domain/auth/service.py
@@ -28,7 +28,7 @@
             "https://github.com/login/oauth/authorize"
             f"?client_id={GITHUB_CLIENT_ID}"
             f"&redirect_uri={GITHUB_REDIRECT_URI}"
-            "&scope=repo,read:org"
+            "&scope=repo,read:org,user:email"
         )
"""
    suggestions = parse_git_diff_to_suggestions(diff_text)
    assert len(suggestions) == 1
    assert suggestions[0]["path"] == "src/agent47/domain/auth/service.py"
    assert "scope=repo,read:org,user:email" in suggestions[0]["body"]
    assert suggestions[0]["line"] == 31
    assert "start_line" not in suggestions[0]


def test_parse_multi_line_suggestion():
    diff_text = """diff --git a/src/agent47/domain/auth/service.py b/src/agent47/domain/auth/service.py
index 9d3910c..1b0a887 100644
--- Clearance
+++ Verification
@@ -57,11 +57,6 @@
     @staticmethod
     def get_user_info(token: str) -> dict:
         \"\"\"Fetch the authenticated user's GitHub profile.\"\"\"
-        gh = Github(token)
-        user = gh.get_user()
-        logger.info("user from github %s", user)
+        # New multi-line block replacement
+        logger.info("loading user...")
+        user = fetch_user(token)
         return {
"""
    suggestions = parse_git_diff_to_suggestions(diff_text)
    assert len(suggestions) == 1
    assert suggestions[0]["path"] == "src/agent47/domain/auth/service.py"
    assert "fetch_user(token)" in suggestions[0]["body"]
    assert suggestions[0]["start_line"] == 60
    assert suggestions[0]["line"] == 62


def test_parse_multiple_hunks():
    diff_text = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -10,3 +10,3 @@
-old line 10
+new line 10
@@ -20,3 +20,3 @@
-old line 20
+new line 20
"""
    suggestions = parse_git_diff_to_suggestions(diff_text)
    assert len(suggestions) == 2
    assert suggestions[0]["line"] == 10
    assert suggestions[1]["line"] == 20


@patch("agent47.agents.graph.detect_base_image")
@patch("agent47.agents.graph.sandbox")
def test_setup_sandbox_node_config_loader(mock_sandbox, mock_detect_image):
    mock_detect_image.return_value = "python:3.10-slim"
    
    # Create temp workspace directory with a mock config file
    with tempfile.TemporaryDirectory() as temp_dir:
        config_data = {
            "rules": [
                "Use logger instead of print",
                "Always write comments"
            ],
            "test_command": "pytest -v tests/unit"
        }
        
        config_path = os.path.join(temp_dir, ".agent47.yaml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)
            
        state = {
            "workspace_dir": temp_dir,
            "error_message": "test",
            "bug_description": "test",
            "relevant_files": [],
            "test_output": "",
            "is_resolved": False,
            "attempt_count": 0,
        }
        
        res = setup_sandbox_node(state)
        
        assert res["custom_rules"] == [
            "Use logger instead of print",
            "Always write comments"
        ]
        assert res["custom_test_command"] == "pytest -v tests/unit"
