import importlib.util
import json
import re
import unittest
from pathlib import Path

from countersign.web import create_app

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("export_postman", ROOT / "scripts" / "export_postman.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

# pages, files and streams a person opens in a browser, not calls of the API
NOT_API = {"/", "/api/stream", "/dashboard", "/dashboard/{path}", "/brand/{name}", "/favicon.ico", "/review/{action_id}"}


def in_collection(node):
    for entry in node["item"]:
        if "item" in entry:
            yield from in_collection(entry)
        else:
            req = entry["request"]
            path = "/" + "/".join(req["url"]["path"])
            yield req["method"], re.sub(r"/\d+(?=/|$)", "/{}", re.sub(r"\{\{[a-z_]+\}\}", "{}", path))


def in_api():
    for path, methods in create_app("sim", llm=None).openapi()["paths"].items():
        path = re.sub(r"\{path:path\}", "{path}", path)
        if path in NOT_API:
            continue
        for method in methods:
            if method == "head":   # a GET route answers HEAD by itself
                continue
            yield method.upper(), re.sub(r"\{[a-z_]+\}", "{}", path)


class PostmanTests(unittest.TestCase):
    def test_every_route_of_the_api_is_in_the_collection(self):
        have = set(in_collection(export.build()))
        missing = sorted(set(in_api()) - have)
        self.assertEqual(missing, [], "add these to scripts/export_postman.py and run it")

    def test_the_committed_file_is_what_the_script_writes(self):
        committed = json.loads(export.OUT.read_text(encoding="utf-8"))
        self.assertEqual(committed, export.build(), "run python scripts/export_postman.py and commit the file")

    def test_no_token_or_real_address_is_in_the_file(self):
        text = export.OUT.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"@gmail\.com|@outlook\.com")
        self.assertIn('"key": "owner_token",\n      "value": ""', text)


if __name__ == "__main__":
    unittest.main()
