import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add src to python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from browser_extractor import (
    clean_web_scraping_artifacts,
    validate_file_path,
    validate_commands,
    extract_and_validate_code,
)


class TestBrowserExtractor(unittest.TestCase):

    def test_clean_web_scraping_artifacts(self):
        messy_html = """
        <div class="message-content">
            <button class="copy-btn">Copy code</button>
            <p>Here is the updated file:</p>
            <pre><code class="language-python">
# path/to/script.py
print("Hello ZeroGravity")
            </code></pre>
            <div class="action-buttons">
                <button>Edit prompt</button>
                <span>Share & export</span>
            </div>
        </div>
        """
        cleaned = clean_web_scraping_artifacts(messy_html)
        self.assertNotIn("Copy code", cleaned)
        self.assertNotIn("Edit prompt", cleaned)
        self.assertNotIn("<button>", cleaned)
        self.assertIn("print(\"Hello ZeroGravity\")", cleaned)

    def test_path_traversal_prevention(self):
        # Path traversal with ../
        valid, msg = validate_file_path("../../etc/passwd", workspace_root="/workspace")
        self.assertFalse(valid)
        self.assertIn("Path traversal attack detected", msg)

        # Path traversal embedded in path
        valid, msg = validate_file_path("src/../../secret.txt", workspace_root="/workspace")
        self.assertFalse(valid)
        self.assertIn("Path traversal attack detected", msg)

        # Absolute path outside workspace
        valid, msg = validate_file_path("C:/Windows/System32/cmd.exe", workspace_root="/workspace")
        self.assertFalse(valid)

        # Valid relative paths
        valid, msg = validate_file_path("services/router/src/app.py", workspace_root="/workspace")
        self.assertTrue(valid)

        valid, msg = validate_file_path("README.md", workspace_root="/workspace")
        self.assertTrue(valid)

    def test_command_safety_validation(self):
        # Dangerous commands
        valid, msg = validate_commands(["rm -rf /", "ls -la"])
        self.assertFalse(valid)
        self.assertIn("Dangerous command blocked", msg)

        valid, msg = validate_commands(["mkfs.ext4 /dev/sda1"])
        self.assertFalse(valid)

        # Safe commands
        valid, msg = validate_commands(["npm test", "python -m unittest discover"])
        self.assertTrue(valid)

    @patch("browser_extractor.httpx.post")
    def test_extract_and_validate_code_with_ollama_mock(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "print('hello from ollama')"
        }
        mock_post.return_value = mock_response

        raw_output = "<button>Copy code</button><pre><code class=\"language-python\"># src/main.py\nprint('raw code')</code></pre>"
        result = extract_and_validate_code(raw_output)

        self.assertTrue(result.get("valid"))
        self.assertEqual(len(result.get("files_to_write", [])), 1)
        self.assertEqual(result["files_to_write"][0]["path"], "src/main.py")
        self.assertEqual(result["files_to_write"][0]["content"], "print('hello from ollama')")

    def test_extract_and_validate_code_path_traversal_rejected(self):
        raw_output = """
        ```python # ../../etc/shadow
        hacked
        ```
        """
        result = extract_and_validate_code(raw_output)
        self.assertFalse(result.get("valid"))
        self.assertIn("Path traversal attack detected", result.get("validation_notes", ""))

    def test_gemini_formatting_variants(self):
        # Variant A: Bold header before code block
        raw_output_a = """
        Here is the Fibonacci script:
        **main.py**
        ```python
        def fibonacci(n):
            return n if n <= 1 else fibonacci(n-1) + fibonacci(n-2)
        print("Hello from ZeroGravity!")
        ```
        """
        res_a = extract_and_validate_code(raw_output_a)
        self.assertTrue(res_a.get("valid"))
        self.assertEqual(len(res_a.get("files_to_write", [])), 1)
        self.assertEqual(res_a["files_to_write"][0]["path"], "main.py")

        # Variant B: Comment on first line inside code block
        raw_output_b = """
        ```python
        # src/auth.py
        import hashlib
        def hash_pw(pw):
            return hashlib.sha256(pw.encode()).hexdigest()
        ```
        """
        res_b = extract_and_validate_code(raw_output_b)
        self.assertTrue(res_b.get("valid"))
        self.assertEqual(res_b["files_to_write"][0]["path"], "src/auth.py")

        # Variant C: Prompt hint fallback
        raw_output_c = """
        ```python
        print("Calculated numbers")
        ```
        """
        # Variant D: Multi-file extraction from Gemini Web DOM (File: <path> headers)
        raw_output_d = """
File: requirements.txt
Plaintext
fastapi
uvicorn
pytest

File: src/database.py
Python
import sqlite3
def get_db(): pass

File: tests/test_api.py
Python
def test_ok(): assert True

Bash
pip install -r requirements.txt
pytest tests/test_api.py
"""
        res_d = extract_and_validate_code(raw_output_d)
        self.assertTrue(res_d.get("valid"))
        self.assertEqual(len(res_d.get("files_to_write", [])), 3)
        paths = [f["path"] for f in res_d["files_to_write"]]
        self.assertEqual(paths, ["requirements.txt", "src/database.py", "tests/test_api.py"])
        self.assertIn("fastapi", res_d["files_to_write"][0]["content"])
        self.assertNotIn("Plaintext", res_d["files_to_write"][0]["content"])
        self.assertIn("pytest tests/test_api.py", res_d.get("commands_to_run", []))


if __name__ == "__main__":
    unittest.main()

