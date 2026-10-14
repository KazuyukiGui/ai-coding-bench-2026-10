import unittest
from config_parser import ConfigError, parse_config


class TestConfigParserHidden(unittest.TestCase):

    def test_01_basic_types_and_sections(self):
        cfg = """
        # Root keys
        app_name = "my_service"
        max_retries = 3
        timeout = 1.5e2
        debug = on
         nothing = None

        [database.primary]
        host = 'localhost'
        port = 5432
        pool_size = 0x10
        flags = [true, false, "read_write", ]

        [database]
        enabled = yes
        """
        res = parse_config(cfg)
        self.assertEqual(res["app_name"], "my_service")
        self.assertEqual(res["max_retries"], 3)
        self.assertEqual(res["timeout"], 150.0)
        self.assertIs(res["debug"], True)
        self.assertIsNone(res["nothing"])
        self.assertIs(res["database"]["enabled"], True)
        self.assertEqual(res["database"]["primary"]["host"], "localhost")
        self.assertEqual(res["database"]["primary"]["port"], 5432)
        self.assertEqual(res["database"]["primary"]["pool_size"], 16)
        self.assertEqual(res["database"]["primary"]["flags"], [True, False, "read_write"])

    def test_02_comments_and_quotes(self):
        cfg = r"""
        a = "hello # not a comment" # this is a comment
        b = 'single # not a comment' # comment
        c = "escaped \" quote # still string" # end
        d = 'backslashes \\ in single quote'
        """
        res = parse_config(cfg)
        self.assertEqual(res["a"], "hello # not a comment")
        self.assertEqual(res["b"], "single # not a comment")
        self.assertEqual(res["c"], 'escaped " quote # still string')
        self.assertEqual(res["d"], r"backslashes \\ in single quote")

    def test_03_line_continuation_and_even_backslashes(self):
        cfg = (
            'path = "C:\\\\path\\\\"\n'
            'next_key = "ok"\n'
            'joined = [1, \\\n'
            '  2, \\\n'
            '  3]\n'
            'str_cont = "hello \\\n'
            '   world"\n'
            'escaped_cont = "ends with backslash \\\\\\\n'
            '   and continues"\n'
        )
        res = parse_config(cfg)
        self.assertEqual(res["path"], "C:\\path\\")
        self.assertEqual(res["next_key"], "ok")
        self.assertEqual(res["joined"], [1, 2, 3])
        self.assertEqual(res["str_cont"], "hello world")
        self.assertEqual(res["escaped_cont"], "ends with backslash \\and continues")

    def test_04_trailing_continuation_at_eof_raises(self):
        cfg = "a = 1 \\\n"
        with self.assertRaises(ConfigError):
            parse_config(cfg)

        cfg2 = "a = 1 \\\n# comment only"
        # Continuing into a comment-only line finishes the continuation on that line
        res = parse_config(cfg2)
        self.assertEqual(res["a"], 1)

    def test_05_assignment_operator_precedence(self):
        # "=" appears before ":=" inside the value
        cfg = """
        [vars]
        x = "expanded"
        normal_with_colon_eq = "a:=b:${x}"
        raw_with_eq = "a=b:${x}"
        raw_assign := "a=b:${x}"
        """
        res = parse_config(cfg)
        self.assertEqual(res["vars"]["normal_with_colon_eq"], "a:=b:expanded")
        self.assertEqual(res["vars"]["raw_with_eq"], "a=b:expanded")
        self.assertEqual(res["vars"]["raw_assign"], "a=b:${x}")

    def test_06_escape_sequences_and_dollar_escape(self):
        cfg = r"""
        v = "VAL"
        s1 = "line1\nline2\t\r\"\\"
        s2 = "literal \$${v} and \${v} and \\${v}"
        s3 := "raw \${v} and \\${v}"
        """
        res = parse_config(cfg)
        self.assertEqual(res["s1"], "line1\nline2\t\r\"\\")
        # \$ -> literal $, ${v} -> VAL
        # \${v} -> literal ${v}
        # \\${v} -> literal \ followed by VAL
        self.assertEqual(res["s2"], "literal $VAL and ${v} and \\VAL")
        self.assertEqual(res["s3"], "raw ${v} and \\${v}")

    def test_07_invalid_escapes_and_quote_boundaries(self):
        bad_cases = [
            r'a = "invalid \a escape"',
            'a = "unterminated',
            'a = "escaped end quote\\"',
            'a = "first" "second"',
            'a = "first" trailing',
            "a = 'first' 'second'",
            "a = 'unterminated",
            'a = unquoted"quote',
            "a = unquoted'quote",
            "a = unquoted with spaces",
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_08_numeric_literals_and_underscores(self):
        cfg = """
        i_dec = -1_000_000
        i_hex = 0xFF_00
        i_oct = 0o755
        i_bin = 0b1010_0101
        f_std = 3.14_15
        f_exp = -2.5e-3
        f_lead_dot = .5
        f_trail_dot = 5.
        inf_str = inf
        nan_str = NaN
        """
        res = parse_config(cfg)
        self.assertEqual(res["i_dec"], -1000000)
        self.assertEqual(res["i_hex"], 0xFF00)
        self.assertEqual(res["i_oct"], 0o755)
        self.assertEqual(res["i_bin"], 0b10100101)
        self.assertAlmostEqual(res["f_std"], 3.1415)
        self.assertAlmostEqual(res["f_exp"], -0.0025)
        self.assertAlmostEqual(res["f_lead_dot"], 0.5)
        self.assertAlmostEqual(res["f_trail_dot"], 5.0)
        self.assertEqual(res["inf_str"], "inf")
        self.assertEqual(res["nan_str"], "NaN")

        bad_nums = [
            "a = 1__000",
            "a = 1000_",
            "a = 0x10_",
            "a = 1._5",
            "a = 1_.5",
            "a = 1e_5",
            "a = 1e5_",
        ]
        for case in bad_nums:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_09_arrays_nested_and_edge_cases(self):
        cfg = """
        empty = []
        single_trailing = [ "a,b", '[1,2]', ]
        nested = [[1, 2], [3, [4, 5]], []]
        with_refs = [${base}, "${base}_str"]
        base = 42
        """
        res = parse_config(cfg)
        self.assertEqual(res["empty"], [])
        self.assertEqual(res["single_trailing"], ["a,b", "[1,2]"])
        self.assertEqual(res["nested"], [[1, 2], [3, [4, 5]], []])
        self.assertEqual(res["with_refs"], [42, "42_str"])

        bad_arrays = [
            "a = [,]",
            "a = [1, , 2]",
            "a = [, 1]",
            "a = [[1, 2]",
            "a = [1, 2]]",
        ]
        for case in bad_arrays:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_10_interpolation_scoping_and_forward_refs(self):
        cfg = """
        global_val = "root_global"
        shared = "root_shared"
        forward_root = ${sec.sub.deep}

        [sec]
        shared = "sec_shared"
        use_local = ${shared}
        use_global = ${global_val}
        use_root_explicit = ${shared}

        [sec.sub]
        deep = ${sec.use_local}
        """
        res = parse_config(cfg)
        self.assertEqual(res["sec"]["use_local"], "sec_shared")
        self.assertEqual(res["sec"]["use_global"], "root_global")
        self.assertEqual(res["forward_root"], "sec_shared")

    def test_11_type_preservation_vs_string_coercion(self):
        cfg = """
        flag = true
        num = 100
        arr = [1, 2]

        [sub]
        k = "v"

        [copy]
        c_flag = ${flag}
        c_flag_str = "${flag}"
        c_num_str = "${num}"
        c_combined = ${num}_000
        c_arr = ${arr}
        c_sec = ${sub}
        """
        res = parse_config(cfg)
        self.assertIs(res["copy"]["c_flag"], True)
        self.assertEqual(res["copy"]["c_flag_str"], "true")
        self.assertEqual(res["copy"]["c_num_str"], "100")
        self.assertEqual(res["copy"]["c_combined"], 100000)
        self.assertEqual(res["copy"]["c_arr"], [1, 2])
        self.assertIsNot(res["copy"]["c_arr"], res["arr"])
        self.assertEqual(res["copy"]["c_sec"], {"k": "v"})
        self.assertIsNot(res["copy"]["c_sec"], res["sub"])

    def test_12_non_scalar_in_string_interpolation_raises(self):
        bad_cases = [
            "n = null\ns = \"val is ${n}\"",
            "n = null\ns = prefix_${n}",
            "arr = [1, 2]\ns = \"${arr}\"",
            "[sec]\na = 1\n[other]\ns = \"${sec}\"",
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_13_env_interpolation(self):
        cfg = """
        port = ${ENV:PORT}
        port_str = "${ENV:PORT}"
        host = ${ENV:HOST:-localhost}
        empty_def = "${ENV:MISSING:-}"
        fallback_with_colon = "${ENV:MISSING:-http://localhost:8080}"
        raw_env := ${ENV:PORT}
        single_env = '${ENV:PORT}'
        """
        env = {"PORT": "8080"}
        res = parse_config(cfg, env=env)
        self.assertEqual(res["port"], 8080)
        self.assertEqual(res["port_str"], "8080")
        self.assertEqual(res["host"], "localhost")
        self.assertEqual(res["empty_def"], "")
        self.assertEqual(res["fallback_with_colon"], "http://localhost:8080")
        self.assertEqual(res["raw_env"], "${ENV:PORT}")
        self.assertEqual(res["single_env"], "${ENV:PORT}")

        with self.assertRaises(ConfigError):
            parse_config("x = ${ENV:UNDEFINED_VAR}", env={})

    def test_14_unquoted_interpolation_producing_spaces_raises(self):
        cfg = """
        greeting = "hello world"
        bad = ${greeting}_suffix
        """
        with self.assertRaises(ConfigError):
            parse_config(cfg)

        cfg_ok = """
        greeting = "hello world"
        direct = ${greeting}
        quoted = "${greeting}_suffix"
        """
        res = parse_config(cfg_ok)
        self.assertEqual(res["direct"], "hello world")
        self.assertEqual(res["quoted"], "hello world_suffix")

    def test_15_circular_reference_detection(self):
        cases = [
            "a = ${a}",
            "a = ${b}\nb = ${a}",
            "a = ${b}\nb = [${c}]\nc = \"${a}\"",
            "[sec]\na = ${sec}\n",
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_16_section_and_key_conflicts_and_naming(self):
        bad_cases = [
            "a = 1\n[a]\nb = 2",
            "[a.b]\nc = 1\n[a]\nb = 2",
            "[]\na = 1",
            "[a..b]\nc = 1",
            "[.a]\nc = 1",
            "[a.]\nc = 1",
            "[123sec]\na = 1",
            "123key = 1",
            "a.b = 1",
            "key = ",
            "a = ${}",
            "a = ${unclosed",
            "a = ${nonexistent}",
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)


if __name__ == "__main__":
    unittest.main()
