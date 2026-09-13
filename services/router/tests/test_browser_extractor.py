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
    check_syntax_sanity,
    resolve_java_path,
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

    def test_typescript_nodejs_extraction(self):
        raw_ts = """
File: package.json
JSON
{
  "name": "zero-gravity-app",
  "version": "1.0.0",
  "scripts": {
    "test": "jest"
  }
}

File: tsconfig.json
JSON
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext"
  }
}

File: src/index.ts
TypeScript
import express, { Request, Response } from 'express';

const app = express();
app.get('/health', (req: Request, res: Response) => {
    res.json({ status: 'ok' });
});

export default app;

Bash
npm install
npm test
"""
        res = extract_and_validate_code(raw_ts)
        self.assertTrue(res.get("valid"))
        self.assertEqual(len(res.get("files_to_write", [])), 3)
        paths = [f["path"] for f in res["files_to_write"]]
        self.assertEqual(paths, ["package.json", "tsconfig.json", "src/index.ts"])
        self.assertIn("zero-gravity-app", res["files_to_write"][0]["content"])
        self.assertIn("npm test", res.get("commands_to_run", []))

    def test_java_spring_boot_extraction_and_package_mapping(self):
        raw_java = """
File: pom.xml
XML
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>demo</artifactId>
    <version>0.0.1-SNAPSHOT</version>
</project>

File: src/main/resources/application.yaml
YAML
server:
  port: 8080
spring:
  application:
    name: demo-service

File: UserController.java
Java
package com.example.demo.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class UserController {
    @GetMapping("/users")
    public String getUsers() {
        return "all users";
    }
}

File: UserControllerTest.java
Java
package com.example.demo.controller;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class UserControllerTest {
    @Test
    void testSample() {
        assertTrue(true);
    }
}

Bash
mvn clean test
"""
        res = extract_and_validate_code(raw_java)
        self.assertTrue(res.get("valid"))
        self.assertEqual(len(res.get("files_to_write", [])), 4)
        paths = [f["path"] for f in res["files_to_write"]]
        self.assertIn("pom.xml", paths)
        self.assertIn("src/main/resources/application.yaml", paths)
        self.assertIn("src/main/java/com/example/demo/controller/UserController.java", paths)
        self.assertIn("src/test/java/com/example/demo/controller/UserControllerTest.java", paths)
        self.assertIn("mvn clean test", res.get("commands_to_run", []))

    def test_yaml_json_syntax_validation(self):
        # Valid YAML
        valid, msg = check_syntax_sanity("application.yaml", "server:\n  port: 8080\n")
        self.assertTrue(valid)

        # Invalid YAML
        valid, msg = check_syntax_sanity("application.yaml", "server: [invalid yaml {")
        self.assertFalse(valid)
        self.assertIn("YAML SyntaxError", msg)

        # Valid JSON
        valid, msg = check_syntax_sanity("package.json", '{"name": "test"}')
        self.assertTrue(valid)

        # Invalid JSON
        valid, msg = check_syntax_sanity("package.json", '{"name": "test",,}')
        self.assertFalse(valid)
        self.assertIn("JSON SyntaxError", msg)

    def test_polyglot_command_safety(self):
        safe_cmds = [
            "npm install",
            "npm run build",
            "npm test",
            "mvn clean install",
            "./mvnw test",
            "gradle test",
            "./gradlew build",
            "pytest tests/",
            "python main.py",
        ]
        valid, msg = validate_commands(safe_cmds)
        self.assertTrue(valid)


if __name__ == "__main__":
    unittest.main()


