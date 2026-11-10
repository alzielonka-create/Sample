import io
import json
import os
import re
import tempfile
import unittest

from addressdb.web import create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(os.path.join(self.tmp.name, "web.db"), secret_key="test")
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def token(self, path="/new"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, path, data=None, token_from="/new", **kw):
        data = dict(data or {})
        data["csrf_token"] = self.token(token_from)
        return self.client.post(path, data=data, **kw)

    def add(self, **fields):
        r = self.post("/new", fields)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True))
        return int(r.headers["Location"].rstrip("/").split("/")[-1])

    def test_empty_state(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("No addresses yet", r.get_data(as_text=True))

    def test_create_view_edit_delete(self):
        aid = self.add(first_name="Ada", last_name="Lovelace", city="London", tags="Work")
        page = self.client.get(f"/{aid}").get_data(as_text=True)
        self.assertIn("Ada Lovelace", page)
        self.assertIn(">work<", page)

        r = self.post(f"/{aid}/edit", {"first_name": "Ada", "last_name": "Lovelace", "city": "Paris"},
                      token_from=f"/{aid}/edit", follow_redirects=True)
        self.assertIn("Paris", r.get_data(as_text=True))

        r = self.post(f"/{aid}/delete", token_from=f"/{aid}", follow_redirects=True)
        self.assertIn("Deleted Ada Lovelace", r.get_data(as_text=True))
        self.assertEqual(self.client.get(f"/{aid}").status_code, 404)

    def test_validation_keeps_input(self):
        r = self.post("/new", {"city": "Lonely Town", "email": "x@example.com"})
        self.assertEqual(r.status_code, 422)
        html = r.get_data(as_text=True)
        self.assertIn("needs a first name", html)
        self.assertIn('value="Lonely Town"', html)

    def test_post_without_csrf_is_rejected(self):
        r = self.client.post("/new", data={"first_name": "Mallory"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("No addresses yet", self.client.get("/").get_data(as_text=True))

    def test_html_is_escaped(self):
        self.add(first_name="<script>alert(1)</script>")
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_search_tag_and_sort(self):
        self.add(first_name="Ada", last_name="Lovelace", city="London", tags="work")
        self.add(first_name="Alan", last_name="Turing", city="Manchester", tags="work,friends")
        self.add(company="Acme", city="Berlin")
        html = self.client.get("/?q=manchester").get_data(as_text=True)
        self.assertIn("Turing", html)
        self.assertNotIn("Lovelace", html)
        html = self.client.get("/?tag=friends").get_data(as_text=True)
        self.assertIn("1 of 3", html)
        html = self.client.get("/?sort=bogus").get_data(as_text=True)
        self.assertLess(html.index("Acme"), html.index("Lovelace"))

    def test_export_and_import(self):
        self.add(first_name="Ada", last_name="Lovelace", notes="Ünïcode ✓")
        r = self.client.get("/export.json")
        self.assertIn("attachment", r.headers["Content-Disposition"])
        data = json.loads(r.data)
        self.assertEqual(data[0]["notes"], "Ünïcode ✓")
        csv_r = self.client.get("/export.csv")
        self.assertTrue(csv_r.data.startswith(b"first_name,"))

        upload = b"first_name,last_name,city\nGrace,Hopper,New York\n,,Nowhere\n"
        r = self.post("/import", {"file": (io.BytesIO(upload), "people.csv")},
                      token_from="/import", content_type="multipart/form-data")
        html = r.get_data(as_text=True)
        self.assertIn("Imported 1 address", html)
        self.assertIn("1 row(s) skipped", html)

        r = self.post("/import", {"file": (io.BytesIO(b"{not json"), "x.json")},
                      token_from="/import", content_type="multipart/form-data")
        self.assertEqual(r.status_code, 422)
        self.assertIn("Invalid JSON", r.get_data(as_text=True))

    def test_duplicates_page(self):
        self.add(first_name="Ada", last_name="Lovelace", street="1 Main")
        self.add(first_name="ada", last_name="lovelace", street="1 main")
        html = self.client.get("/duplicates").get_data(as_text=True)
        self.assertNotIn("No duplicates found", html)

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")


if __name__ == "__main__":
    unittest.main()
