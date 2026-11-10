import io
import json
import os
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout

from addressdb import Address, AddressDB, ValidationError
from addressdb.cli import main


class AddressDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.db")
        self.db = AddressDB(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _sample(self, **kw):
        base = dict(first_name="Ada", last_name="Lovelace", street="12 St James's Sq",
                    city="London", postal_code="SW1Y 4JH", country="UK",
                    email="ada@example.com", tags="Friends, work")
        base.update(kw)
        return self.db.add(Address(**base))

    def test_add_and_get(self):
        a = self._sample()
        self.assertIsNotNone(a.id)
        self.assertEqual(a.tags, "friends,work")
        self.assertEqual(self.db.get(a.id).city, "London")
        self.assertIsNotNone(a.created_at)

    def test_requires_name_or_company(self):
        with self.assertRaises(ValidationError):
            self.db.add(Address(city="Nowhere"))
        self.assertEqual(self.db.add(Address(company="Acme")).company, "Acme")

    def test_rejects_bad_email(self):
        with self.assertRaises(ValidationError):
            self._sample(email="not-an-email")

    def test_update(self):
        a = self._sample()
        b = self.db.update(a.id, city="Paris", tags="travel")
        self.assertEqual(b.city, "Paris")
        self.assertEqual(b.tags, "travel")
        with self.assertRaises(ValidationError):
            self.db.update(a.id, bogus="x")
        with self.assertRaises(KeyError):
            self.db.update(9999, city="x")

    def test_delete(self):
        a = self._sample()
        self.assertTrue(self.db.delete(a.id))
        self.assertFalse(self.db.delete(a.id))
        self.assertIsNone(self.db.get(a.id))

    def test_search_and_filters(self):
        self._sample()
        self._sample(first_name="Alan", last_name="Turing", city="Manchester",
                     email="alan@example.com", tags="work")
        self._sample(first_name="Grace", last_name="Hopper", city="New York",
                     country="USA", email="", tags="navy")
        self.assertEqual(len(self.db.search("lovelace")), 1)
        self.assertEqual(len(self.db.search("example.com")), 2)
        self.assertEqual(len(self.db.search("alan manchester")), 1)
        self.assertEqual(len(self.db.search("alan london")), 0)
        self.assertEqual(len(self.db.list(tag="work")), 2)
        self.assertEqual(len(self.db.list(tag="WORK")), 2)
        self.assertEqual(len(self.db.list(tag="wor")), 0)  # whole-tag match only
        self.assertEqual(len(self.db.list(country="usa")), 1)
        names = [a.last_name for a in self.db.list()]
        self.assertEqual(names, ["Hopper", "Lovelace", "Turing"])
        self.assertEqual(len(self.db.list(limit=2)), 2)

    def test_search_is_injection_safe(self):
        self._sample()
        self.assertEqual(self.db.search("'; DROP TABLE addresses; --"), [])
        self.assertEqual(self.db.count(), 1)

    def test_duplicates(self):
        self._sample()
        self._sample(first_name="ADA")
        self._sample(first_name="Alan", last_name="Turing")
        groups = self.db.find_duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_csv_and_json_roundtrip(self):
        self._sample()
        self._sample(first_name="Alan", last_name="Turing", notes="Ünïcode ✓")
        for ext in ("csv", "json"):
            out = os.path.join(self.tmp.name, f"out.{ext}")
            getattr(self.db, f"export_{ext}")(out)
            with AddressDB(os.path.join(self.tmp.name, f"copy_{ext}.db")) as other:
                n, errors = getattr(other, f"import_{ext}")(out)
                self.assertEqual((n, errors), (2, []))
                self.assertEqual(other.search("Turing")[0].notes, "Ünïcode ✓")

    def test_import_skips_invalid_rows(self):
        n, errors = self.db.import_records([
            {"first_name": "Ok"}, {"city": "no name"}, {"company": "X", "email": "bad"},
        ])
        self.assertEqual(n, 1)
        self.assertEqual(len(errors), 2)

    def test_formatted(self):
        a = self._sample(company="Analytical Engines", state="")
        self.assertEqual(
            a.formatted(),
            "Ada Lovelace (Analytical Engines)\n12 St James's Sq\nSW1Y 4JH London\nUK",
        )


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "cli.db")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--db", self.db, *argv])
        return code, buf.getvalue()

    def test_full_flow(self):
        code, out = self.run_cli("add", "--first", "Ada", "--last", "Lovelace",
                                 "--city", "London", "--tags", "work")
        self.assertEqual(code, 0)
        self.assertIn("Added address 1", out)
        code, out = self.run_cli("search", "ada", "--json")
        self.assertEqual(json.loads(out)[0]["city"], "London")
        code, out = self.run_cli("update", "1", "--city", "Paris")
        self.assertEqual(code, 0)
        code, out = self.run_cli("show", "1")
        self.assertIn("Paris", out)
        code, out = self.run_cli("list")
        self.assertIn("Lovelace", out)
        code, out = self.run_cli("delete", "1", "--yes")
        self.assertEqual(code, 0)
        code, out = self.run_cli("stats")
        self.assertIn("0 address(es)", out)

    def test_errors_return_nonzero(self):
        with redirect_stdout(io.StringIO()), \
             open(os.devnull, "w") as devnull, \
             unittest.mock.patch("sys.stderr", devnull):
            self.assertEqual(main(["--db", self.db, "add", "--city", "X"]), 2)
            self.assertEqual(main(["--db", self.db, "show", "42"]), 1)


if __name__ == "__main__":
    unittest.main()
