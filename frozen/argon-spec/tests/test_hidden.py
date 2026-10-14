import unittest
from config_parser import parse_config, ConfigError


class TestConfigParserHidden(unittest.TestCase):

    def test_01_basic_types_and_comments(self):
        cfg = """
        # Line comment with #
        // Line comment with //
        /* Multi-line
           block comment */
        int_val = 42
        neg_int = -100
        pos_int = +7
        zero_val = -0
        float_val = 3.1415
        exp_val = -2.5e-2
        bool_t = true
        bool_f = false
        null_val = null
        str_val = "hello\\nworld\\t\\"escaped\\"\\\\\\$100\\r"
        empty_list = []
        nested_list = [1, [2, 3,], ]
        """
        res = parse_config(cfg)
        self.assertEqual(res["int_val"], 42)
        self.assertIs(type(res["int_val"]), int)
        self.assertEqual(res["neg_int"], -100)
        self.assertEqual(res["pos_int"], 7)
        self.assertEqual(res["zero_val"], 0)
        self.assertAlmostEqual(res["float_val"], 3.1415)
        self.assertAlmostEqual(res["exp_val"], -0.025)
        self.assertIs(res["bool_t"], True)
        self.assertIs(res["bool_f"], False)
        self.assertIsNone(res["null_val"])
        self.assertEqual(res["str_val"], "hello\nworld\t\"escaped\"\\$100\r")
        self.assertEqual(res["empty_list"], [])
        self.assertEqual(res["nested_list"], [1, [2, 3]])

    def test_02_semicolons_and_reserved_words_as_keys(self):
        cfg = """
        ;;
        true = false; false = true; null = "not_null";
        block.true.null {
            false = [true, false, null]
        };
        ref_test = ${block.true.null.false}
        """
        res = parse_config(cfg)
        self.assertIs(res["true"], False)
        self.assertIs(res["false"], True)
        self.assertEqual(res["null"], "not_null")
        self.assertEqual(res["block"]["true"]["null"]["false"], [True, False, None])
        self.assertEqual(res["ref_test"], [True, False, None])

    def test_03_deep_merge_and_overwrites(self):
        cfg = """
        a.b.x = 1
        a {
            b {
                y = 2
                x = 10
            }
            c = 3
        }
        a.b.z = 30
        """
        res = parse_config(cfg)
        self.assertEqual(res, {
            "a": {
                "b": {"x": 10, "y": 2, "z": 30},
                "c": 3,
            }
        })

    def test_04_operators_and_line_continuation(self):
        cfg = """
        num_sum = 10 +
                  20 + -5
        float_sum = 10 + 0.5
        str_concat = "foo" +
                     "bar" + "baz"
        list_concat = [1, 2] +
                      [3] + []
        """
        res = parse_config(cfg)
        self.assertEqual(res["num_sum"], 25)
        self.assertIs(type(res["num_sum"]), int)
        self.assertEqual(res["float_sum"], 10.5)
        self.assertIs(type(res["float_sum"]), float)
        self.assertEqual(res["str_concat"], "foobarbaz")
        self.assertEqual(res["list_concat"], [1, 2, 3])

    def test_05_interpolation_and_escaped_interpolation(self):
        cfg = """
        s = "str"
        i = 99
        f = 1.5
        bt = true
        bf = false
        n = null
        combined = "${s}|${i}|${f}|${bt}|${bf}|${n}|\\${not_interp}"
        """
        res = parse_config(cfg)
        self.assertEqual(res["combined"], "str|99|1.5|true|false|null|${not_interp}")

    def test_06_lexical_scope_and_shadowing(self):
        cfg = """
        x = "global_x"
        y = "global_y"
        db {
            host = "db_global"
            port = 5432
        }
        service {
            x = "service_x"
            inner {
                val_x = ${x}
                val_y = ${y}
                val_db = "${db.host}:${db.port}"
            }
        }
        """
        res = parse_config(cfg)
        self.assertEqual(res["service"]["inner"]["val_x"], "service_x")
        self.assertEqual(res["service"]["inner"]["val_y"], "global_y")
        self.assertEqual(res["service"]["inner"]["val_db"], "db_global:5432")

    def test_07_shadowing_does_not_fallback_on_partial_match(self):
        cfg = """
        db {
            host = "global_host"
            port = 5432
        }
        app {
            db {
                host = "local_host"
            }
            # app.db exists and shadows root db, so db.port must fail!
            target_port = ${db.port}
        }
        """
        with self.assertRaises(ConfigError):
            parse_config(cfg)

    def test_08_forward_references_and_list_immutability(self):
        cfg = """
        combined = ${base_list} + [4]
        base_list = ${initial} + [2, 3]
        initial = [1]
        """
        res = parse_config(cfg)
        self.assertEqual(res["initial"], [1])
        self.assertEqual(res["base_list"], [1, 2, 3])
        self.assertEqual(res["combined"], [1, 2, 3, 4])

    def test_09_env_variables(self):
        cfg = """
        a = ${env:HOST}
        b = ${env:PORT:-8080}
        c = ${env:EMPTY_VAR:-fallback}
        d = ${env:MISSING_VAR:-}
        e = "url=http://${env:HOST}:${env:PORT:-9000}/api"
        """
        env = {"HOST": "127.0.0.1", "EMPTY_VAR": ""}
        res = parse_config(cfg, env=env)
        self.assertEqual(res["a"], "127.0.0.1")
        self.assertEqual(res["b"], "8080")
        self.assertEqual(res["c"], "fallback")
        self.assertEqual(res["d"], "")
        self.assertEqual(res["e"], "url=http://127.0.0.1:9000/api")

        # Missing required env var should raise ConfigError
        with self.assertRaises(ConfigError):
            parse_config("x = ${env:NOT_SET}", env={})

    def test_10_inheritance_and_late_binding(self):
        cfg = """
        global_prefix = "v1"

        base_tpl {
            name = "default"
            port = 80
            endpoint = "${global_prefix}/${name}:${port}"
            nested {
                enabled = true
                 label = "lbl-${name}"
            }
        }

        mid_tpl : base_tpl {
            port = 8080
            nested {
                retries = 3
            }
        }

        prod_svc : mid_tpl {
            global_prefix = "v2"
            name = "auth"
        }
        """
        res = parse_config(cfg)
        self.assertEqual(res["base_tpl"]["endpoint"], "v1/default:80")
        self.assertEqual(res["base_tpl"]["nested"]["label"], "lbl-default")
        self.assertEqual(res["mid_tpl"]["endpoint"], "v1/default:8080")
        self.assertEqual(res["mid_tpl"]["nested"], {"enabled": True, "label": "lbl-default", "retries": 3})
        self.assertEqual(res["prod_svc"]["endpoint"], "v2/auth:8080")
        self.assertEqual(res["prod_svc"]["nested"], {"enabled": True, "label": "lbl-auth", "retries": 3})

    def test_11_cycle_detection_variables_and_blocks(self):
        # Direct variable cycle
        with self.assertRaises(ConfigError):
            parse_config("a = ${a}")

        # Mutual variable cycle
        with self.assertRaises(ConfigError):
            parse_config("a = ${b}\nb = ${c}\nc = ${a}")

        # Block inheritance cycle
        with self.assertRaises(ConfigError):
            parse_config("a : b {}\nb : a {}")

        # Self / ancestor inheritance cycle
        with self.assertRaises(ConfigError):
            parse_config("a { b : a {} }")

        with self.assertRaises(ConfigError):
            parse_config("a : a.b { b {} }")

    def test_12_type_conflicts_and_invalid_operations(self):
        # Overwriting block with scalar
        with self.assertRaises(ConfigError):
            parse_config("a { x = 1 }\na = 2")

        # Overwriting scalar with block
        with self.assertRaises(ConfigError):
            parse_config("a = 2\na { x = 1 }")

        # Traversing scalar in dotted path
        with self.assertRaises(ConfigError):
            parse_config("a = 2\na.b = 3")

        # Inheritance type conflict (block in parent, scalar in child)
        with self.assertRaises(ConfigError):
            parse_config("p { sub { x = 1 } }\nc : p { sub = 10 }")

        # Invalid '+' combinations
        for bad_expr in [
            '"str" + 10',
            '10 + "str"',
            'true + false',
            'true + 1',
            '[1] + 2',
            'null + null',
        ]:
            with self.assertRaises(ConfigError, msg=f"Failed to reject: {bad_expr}"):
                parse_config(f"x = {bad_expr}")

        # Interpolating list or block into string
        with self.assertRaises(ConfigError):
            parse_config('arr = [1, 2]\ns = "val: ${arr}"')

        # Referencing block as value
        with self.assertRaises(ConfigError):
            parse_config('b { x = 1 }\nv = ${b}')

    def test_13_syntax_and_lexical_errors(self):
        bad_configs = [
            'a = 01',                  # leading zero in int
            'a = -007',                # leading zero in negative int
            'a = 01.5',                # leading zero in float
            'a = .5',                  # leading dot in float
            'a = 5.',                  # trailing dot in float
            'a = "unterminated',       # unterminated string
            'a = "line\nbreak"',       # raw newline in string
            'a = "bad \\q escape"',    # invalid escape
            '/* unclosed comment',     # unclosed block comment
            'a = 1 b = 2',             # missing separator between statements
            'a..b = 1',                # double dot in path
            '.a = 1',                  # leading dot in path
            'a. = 1',                  # trailing dot in path
            'a = [1,,2]',              # double comma in list
            'a = [,]',                 # empty comma in list
            'a = "hello"\n + "world"', # newline before '+'
            'b : p1 {}\nb : p2 {}',    # multiple inheritance on same block
        ]
        for cfg in bad_configs:
            with self.assertRaises(ConfigError, msg=f"Failed to raise ConfigError for:\n{cfg}"):
                parse_config(cfg)

    def test_14_hyphenated_identifiers_and_subtraction_lookalike(self):
        cfg = """
        my-service_1 {
            max-retry-count = 5
            base-val = 10
            calc = ${base-val} + -3
            ref-val = ${my-service_1.max-retry-count}
        }
        """
        res = parse_config(cfg)
        self.assertEqual(res["my-service_1"]["max-retry-count"], 5)
        self.assertEqual(res["my-service_1"]["calc"], 7)
        self.assertEqual(res["my-service_1"]["ref-val"], 5)

    def test_15_inheritance_with_pre_existing_dotted_definitions(self):
        cfg = """
        tpl {
            a = 1
            b = 2
            nested {
                x = 10
                y = 20
            }
        }
        # Define part of child before the block with ': tpl'
        child.a = 100
        child.nested.x = 1000
        child : tpl {
            b = 200
        }
        child.nested.z = 3000
        """
        res = parse_config(cfg)
        self.assertEqual(res["child"], {
            "a": 100,
            "b": 200,
            "nested": {
                "x": 1000,
                "y": 20,
                "z": 3000,
            }
        })


if __name__ == "__main__":
    unittest.main()
