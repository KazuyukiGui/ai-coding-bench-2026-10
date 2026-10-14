import unittest

import iniconf
from iniconf import Config, ConfigError, parse


BASIC = """\
# 全体の設定
[DEFAULT]
timeout = 30
debug = no

[server]
Host = example.local
port = 8080
; コメント
debug = Yes

[paths]
search = /usr/lib
    /opt/lib
\t/srv/lib
"""


class ExistingBehaviorTest(unittest.TestCase):
    def test_basic_get_and_case_insensitive_keys(self):
        c = parse(BASIC)
        self.assertEqual(c.get("server", "host"), "example.local")
        self.assertEqual(c.get("server", "HOST"), "example.local")
        self.assertEqual(c.getint("server", "port"), 8080)
        self.assertIs(c.getbool("server", "debug"), True)
        self.assertIs(c.getbool("paths", "debug"), False)
        self.assertEqual(c.get("paths", "timeout"), "30")
        self.assertEqual(c.get("paths", "search"), "/usr/lib\n/opt/lib\n/srv/lib")

    def test_sections_and_keys_order(self):
        c = parse(BASIC)
        self.assertEqual(c.sections(), ["server", "paths"])
        self.assertTrue(c.has_section("server"))
        self.assertFalse(c.has_section("DEFAULT"))
        self.assertFalse(c.has_section("Server"))
        self.assertEqual(c.keys("server"), ["host", "port", "debug", "timeout"])
        self.assertEqual(c.keys("DEFAULT"), ["timeout", "debug"])
        self.assertEqual(
            c.items("paths"),
            [("search", "/usr/lib\n/opt/lib\n/srv/lib"), ("timeout", "30"), ("debug", "no")],
        )

    def test_missing_and_default(self):
        c = parse(BASIC)
        with self.assertRaises(KeyError):
            c.get("server", "nothing")
        with self.assertRaises(KeyError):
            c.get("nosuch", "host")
        self.assertEqual(c.get("server", "nothing", "x"), "x")
        self.assertIsNone(c.get("nosuch", "host", None))
        self.assertEqual(c.getint("server", "nothing", 7), 7)
        self.assertEqual(c.getbool("server", "nothing", "keep"), "keep")
        with self.assertRaises(ValueError):
            c.getbool("server", "host")

    def test_parse_errors_with_line_numbers(self):
        cases = [
            ("a = 1\n", 1),
            ("[s]\na = 1\n\n  b\n", 4),
            ("[s]\na = 1\n# c\n  b\n", 4),
            ("[s]\na = 1\n[t]\nb = 2\n[s]\nA = 3\n", 6),
            ("[s]\njust text\n", 2),
            ("[s]\n[ ]\n", 2),
            ("[s\n", 1),
            ("[s]\n = 1\n", 2),
        ]
        for text, lineno in cases:
            with self.subTest(text=text):
                with self.assertRaises(ConfigError) as cm:
                    parse(text)
                self.assertEqual(cm.exception.lineno, lineno)

    def test_repeated_section_merges_and_crlf(self):
        c = parse("[a]\r\nx = 1\r\n[b]\r\ny = 2\r\n[a]\r\nz = 3\r\n")
        self.assertEqual(c.sections(), ["a", "b"])
        self.assertEqual(c.keys("a"), ["x", "z"])
        self.assertEqual(c.get("a", "z"), "3")

    def test_set_and_dump(self):
        c = parse(BASIC)
        c.set("new", "Key", "v")
        c.set("DEFAULT", "extra", "e")
        self.assertEqual(c.sections(), ["server", "paths", "new"])
        self.assertEqual(c.get("new", "key"), "v")
        expected = (
            "[DEFAULT]\ntimeout = 30\ndebug = no\nextra = e\n\n"
            "[server]\nhost = example.local\nport = 8080\ndebug = Yes\n\n"
            "[paths]\nsearch = /usr/lib\n    /opt/lib\n    /srv/lib\n\n"
            "[new]\nkey = v\n"
        )
        self.assertEqual(c.dump(), expected)
        again = parse(c.dump())
        self.assertEqual(again.dump(), expected)
        self.assertEqual(Config().dump(), "")
        with self.assertRaises(TypeError):
            c.set("new", "n", 5)


class InterpolationTest(unittest.TestCase):
    def test_same_section_and_other_section(self):
        c = parse(
            "[base]\nroot = /srv\n\n"
            "[app]\nname = shop\nDir = ${base:root}/${name}\nlog = ${dir}/log\n"
        )
        self.assertEqual(c.get("app", "dir"), "/srv/shop")
        self.assertEqual(c.get("app", "log"), "/srv/shop/log")

    def test_dollar_rules(self):
        c = parse(
            "[s]\n"
            "a = 1\n"
            "price = 5$\n"
            "plain = $x and $ y\n"
            "triple = a$$$b\n"
            "esc = $${a}\n"
            "mix = $$$${a}\n"
            "brace = ${a}}\n"
            "first = {${a}$\n"
        )
        self.assertEqual(c.get("s", "price"), "5$")
        self.assertEqual(c.get("s", "plain"), "$x and $ y")
        self.assertEqual(c.get("s", "triple"), "a$$b")
        self.assertEqual(c.get("s", "esc"), "${a}")
        self.assertEqual(c.get("s", "mix"), "$${a}")
        self.assertEqual(c.get("s", "brace"), "1}")
        self.assertEqual(c.get("s", "first"), "{1$")

    def test_result_is_not_rescanned(self):
        c = parse("[s]\na = $${b}\nb = oops\nc = <${a}>\nd = $$$$\ne = ${d}${d}\n")
        self.assertEqual(c.get("s", "c"), "<${b}>")
        self.assertEqual(c.get("s", "e"), "$$$$")

    def test_default_value_uses_requesting_section(self):
        c = parse(
            "[DEFAULT]\nurl = http://${host}:${port}/\nport = 80\n\n"
            "[web]\nhost = w.local\n\n"
            "[api]\nhost = a.local\nport = 9000\n\n"
            "[client]\nhost = c.local\ntarget = ${web:url}\nall = ${api:url}|${url}\n"
        )
        self.assertEqual(c.get("web", "url"), "http://w.local:80/")
        self.assertEqual(c.get("api", "url"), "http://a.local:9000/")
        # ${web:url} は DEFAULT から借りた値だが、展開の文脈は web
        self.assertEqual(c.get("client", "target"), "http://w.local:80/")
        self.assertEqual(c.get("client", "all"), "http://a.local:9000/|http://c.local:80/")
        with self.assertRaises(iniconf.InterpolationError):
            c.get("DEFAULT", "url")

    def test_default_section_reference(self):
        c = parse(
            "[DEFAULT]\npath = /usr\nhost = d.local\nurl = //${host}\n\n"
            "[s]\npath = ${DEFAULT:path}/local\nhost = s.local\nown = ${url}\nbase = ${DEFAULT:url}\n"
        )
        self.assertEqual(c.get("s", "path"), "/usr/local")
        self.assertEqual(c.get("s", "own"), "//s.local")
        self.assertEqual(c.get("s", "base"), "//d.local")
        self.assertEqual(c.get("DEFAULT", "url"), "//d.local")

    def test_cycles(self):
        c = parse(
            "[s]\nself = x${self}\na = ${b}\nb = ${c}\nc = ${t:x}\n"
            "path = ${path}/bin\n\n[t]\nx = ${s:a}\n"
        )
        for key in ("self", "a", "b", "c", "path"):
            with self.subTest(key=key):
                with self.assertRaises(iniconf.InterpolationError) as cm:
                    c.get("s", key)
                self.assertIsInstance(cm.exception, ConfigError)
                self.assertIsNone(cm.exception.lineno)
        with self.assertRaises(iniconf.InterpolationError):
            c.get("t", "x")

    def test_case_insensitive_key_in_cycle_detection(self):
        c = parse("[s]\na = ${B}\nb = ${A}\n")
        with self.assertRaises(iniconf.InterpolationError):
            c.get("s", "A")

    def test_repeated_reference_is_not_a_cycle(self):
        c = parse(
            "[s]\nd = 1\nb = ${d}${d}\nc = ${D}\na = ${b}-${c}-${b}\n"
            "deep = ${s:a}${a}\n"
        )
        self.assertEqual(c.get("s", "a"), "11-1-11")
        self.assertEqual(c.get("s", "deep"), "11-1-1111-1-11")

    def test_missing_references(self):
        c = parse(
            "[web]\nhost = h\n\n[s]\nhost = local\n"
            "k = ${nothing}\n"
            "sec = ${nosuch:host}\n"
            "case = ${Web:host}\n"
            "ok = ${WEB_NOT:x}\n"
            "spaced = ${ host }\n"
        )
        for key in ("k", "sec", "case", "ok", "spaced"):
            with self.subTest(key=key):
                with self.assertRaises(iniconf.InterpolationError):
                    c.get("s", key)
                with self.assertRaises(iniconf.InterpolationError):
                    c.get("s", key, "fallback")

    def test_malformed_references(self):
        c = parse(
            "[s]\na = 1\n"
            "open = x${a\n"
            "empty = ${}\n"
            "nosec = ${:a}\n"
            "nokey = ${s:}\n"
            "nested = ${a${a}}\n"
        )
        for key in ("open", "empty", "nosec", "nokey", "nested"):
            with self.subTest(key=key):
                with self.assertRaises(iniconf.InterpolationError):
                    c.get("s", key)

    def test_colon_splits_at_first(self):
        c = parse("[s]\nA:B = 1\n\n[t]\nv = ${s:a:b}\nw = ${s:A:B}\n")
        self.assertEqual(c.get("t", "v"), "1")
        self.assertEqual(c.get("t", "w"), "1")

    def test_ref_key_case_insensitive_section_case_sensitive(self):
        c = parse("[Web]\nhost = h\n\n[s]\nx = ${Web:HOST}\ny = ${HoSt}\nhost = local\n")
        self.assertEqual(c.get("s", "x"), "h")
        self.assertEqual(c.get("s", "y"), "local")

    def test_multiline_values(self):
        c = parse("[s]\nlist = a\n    ${x}\nx = 1\ny = [${list}]\n")
        self.assertEqual(c.get("s", "list"), "a\n1")
        self.assertEqual(c.get("s", "y"), "[a\n1]")

    def test_raw_and_items(self):
        c = parse("[DEFAULT]\nd = ${n}!\n\n[s]\nn = 3\nm = $$${n}\n")
        self.assertEqual(c.get("s", "m"), "$3")
        self.assertEqual(c.get("s", "m", raw=True), "$$${n}")
        self.assertEqual(c.get("s", "zz", "${n}", raw=True), "${n}")
        self.assertEqual(c.items("s"), [("n", "3"), ("m", "$3"), ("d", "3!")])
        self.assertEqual(
            c.items("s", raw=True), [("n", "3"), ("m", "$$${n}"), ("d", "${n}!")]
        )

    def test_items_raises_on_bad_reference(self):
        c = parse("[s]\na = ok\nb = ${missing}\n")
        with self.assertRaises(iniconf.InterpolationError):
            c.items("s")
        self.assertEqual(c.items("s", raw=True), [("a", "ok"), ("b", "${missing}")])

    def test_default_argument_not_interpolated(self):
        c = parse("[s]\nn = 1\n")
        self.assertEqual(c.get("s", "missing", "${n}"), "${n}")
        self.assertEqual(c.get("s", "missing", default="$$"), "$$")
        self.assertEqual(c.getint("s", "missing", "${n}"), "${n}")
        with self.assertRaises(KeyError):
            c.get("s", "missing")

    def test_getint_getbool_use_expanded_value(self):
        c = parse(
            "[DEFAULT]\nbase = 8000\nflag = ON\n\n"
            "[s]\nport = ${base}\nenabled = ${flag}\nbad = ${base}x\n"
        )
        self.assertEqual(c.getint("s", "port"), 8000)
        self.assertIs(c.getbool("s", "enabled"), True)
        with self.assertRaises(ValueError):
            c.getint("s", "bad")
        c.set("s", "broken", "${nope}")
        with self.assertRaises(iniconf.InterpolationError):
            c.getint("s", "broken", 1)
        with self.assertRaises(iniconf.InterpolationError):
            c.getbool("s", "broken", False)

    def test_lazy_expansion_and_dump_keeps_raw(self):
        text = "[s]\na = ${b}\nb = ${a}\nc = $$5\n"
        c = parse(text)
        self.assertEqual(c.dump(), text)
        self.assertEqual(c.get("s", "c"), "$5")
        c.set("s", "b", "fixed")
        self.assertEqual(c.get("s", "a"), "fixed")
        c.set("s", "b", "${c}${c}")
        self.assertEqual(c.get("s", "a"), "$5$5")
        self.assertEqual(c.get("s", "b", raw=True), "${c}${c}")

    def test_interpolation_disabled(self):
        c = parse("[s]\na = 1\nb = ${a}$$\nc = ${missing\n", interpolation=False)
        self.assertEqual(c.get("s", "b"), "${a}$$")
        self.assertEqual(c.get("s", "c"), "${missing")
        self.assertEqual(c.get("s", "b", raw=True), "${a}$$")
        self.assertEqual(c.items("s"), [("a", "1"), ("b", "${a}$$"), ("c", "${missing")])
        plain = Config(interpolation=False)
        plain.set("s", "x", "${y}")
        self.assertEqual(plain.get("s", "x"), "${y}")
        enabled = Config()
        enabled.set("s", "y", "2")
        enabled.set("s", "x", "${y}")
        self.assertEqual(enabled.get("s", "x"), "2")

    def test_interpolation_error_is_config_error(self):
        self.assertTrue(issubclass(iniconf.InterpolationError, ConfigError))
        c = parse("[s]\na = ${b}\n")
        with self.assertRaises(ConfigError) as cm:
            c.get("s", "a")
        self.assertIsNone(cm.exception.lineno)


if __name__ == "__main__":
    unittest.main()
