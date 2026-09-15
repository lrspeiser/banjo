"""The floating-point audit (scripts/check-fp-model.py): how it reads options,
command lines, response files and sources, and -- on a real configure of
tests/fp_model_audit -- that it names exactly the files that leave the model,
in exactly the configurations that make them leave it.

    python tests/fp_model_audit_tests.py

The fixture is configured with the generator and compiler in
BANJO_FP_FIXTURE_GENERATOR, BANJO_FP_FIXTURE_PLATFORM and BANJO_FP_FIXTURE_CXX
(ctest passes the build's own). With BANJO_FP_FIXTURE_REQUIRED=1 a fixture
that cannot be configured fails instead of skipping.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_fp_model", ROOT / "scripts" / "check-fp-model.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

JOLT_MSVC = ("/DWIN32 /D_WINDOWS  /Zc:__cplusplus /Gm- /MP /nologo /diagnostics:classic /FC /fp:except- "
             "/Zc:inline /Zi /GR- /wd4577 /fp:fast /GS- /Gy /O2 /Oi /Ot -std:c++17 -MD").split()
JOLT_GNU = "-fno-rtti -fno-exceptions -Wno-stringop-overflow -Wno-psabi -ffp-contract=fast -O3".split()


class CommandLines(unittest.TestCase):
    def test_windows_splitting_follows_commandlinetoargvw(self):
        self.assertEqual(audit.split_windows(r'a "b c" d'), ["a", "b c", "d"])
        self.assertEqual(audit.split_windows(r'"a\"b"'), ['a"b'])
        self.assertEqual(audit.split_windows(r'a\\"b c"'), ["a\\b c"])
        self.assertEqual(audit.split_windows(r'C:\dir\file.cpp'), [r"C:\dir\file.cpp"])
        self.assertEqual(audit.split_windows('"" x'), ["", "x"])

    def test_response_files_are_expanded_in_utf16_and_utf8_and_nested(self):
        with tempfile.TemporaryDirectory() as d:
            inner = Path(d) / "inner.rsp"
            inner.write_bytes(b"\xff\xfe" + "/fp:fast".encode("utf-16-le"))
            outer = Path(d) / "outer.rsp"
            outer.write_text(f'/O2 "@{inner}"\r\n/nologo', encoding="utf-8")
            args = audit.expand_response_files(["/fp:precise", f"@{outer}", "/c"], "msvc")
            self.assertEqual(args, ["/fp:precise", "/O2", "/fp:fast", "/nologo", "/c"])
            self.assertEqual(audit.msvc_problems(args), ["/fp:fast"])

    def test_a_missing_response_file_is_an_audit_error_not_a_pass(self):
        with self.assertRaises(audit.AuditError):
            audit.expand_response_files(["@does-not-exist.rsp"], "msvc")


class MsvcRules(unittest.TestCase):
    def test_jolts_own_flags_with_the_model_after_them_keep_it(self):
        self.assertEqual(audit.msvc_problems(JOLT_MSVC + ["/arch:AVX2", "/fp:precise"]), [])

    def test_the_last_model_counts(self):
        self.assertEqual(audit.msvc_problems(JOLT_MSVC), ["/fp:fast"])
        self.assertEqual(audit.msvc_problems(["/fp:precise", "-fp:fast"]), ["/fp:fast"])
        self.assertEqual(audit.msvc_problems(["/fp:precise", "/fp:strict"]), ["/fp:strict"])
        self.assertEqual(audit.msvc_problems([]), [])

    def test_contraction_and_fast_transcendentals_are_refused(self):
        self.assertEqual(audit.msvc_problems(["/fp:precise", "/fp:contract"]), ["/fp:contract"])
        self.assertEqual(audit.msvc_problems(["/Qfast_transcendentals"]), ["/Qfast_transcendentals is not in the profile"])

    def test_an_unknown_floating_point_option_fails_closed(self):
        self.assertTrue(audit.msvc_problems(["/fp:precise", "/fp:mystery"])[0].startswith("/fp:mystery"))

    def test_cl_is_read_before_the_command_and_cl_underscore_after(self):
        command = ["/fp:precise"]
        self.assertEqual(audit.msvc_problems(audit.split_windows("/fp:fast") + command), [])
        self.assertEqual(audit.msvc_problems(command + audit.split_windows("/fp:fast")), ["/fp:fast"])


class GnuRules(unittest.TestCase):
    MODEL = ["-fno-fast-math", "-ffp-contract=off"]

    def test_jolts_own_flags_with_the_model_after_them_keep_it(self):
        self.assertEqual(audit.gnu_problems(JOLT_GNU + self.MODEL + ["-mavx2", "-mfma"]), [])

    def test_contraction_has_to_be_said_and_said_last(self):
        self.assertEqual(audit.gnu_problems(["-O3", "-mfma"]),
                         ["no -ffp-contract=off, so the compiler would contract"])
        self.assertEqual(audit.gnu_problems(JOLT_GNU), ["-ffp-contract=fast"])
        self.assertEqual(audit.gnu_problems(self.MODEL + ["-ffp-contract=on"]), ["-ffp-contract=on"])

    def test_fast_math_is_refused_however_it_comes(self):
        self.assertEqual(audit.gnu_problems(self.MODEL + ["-ffast-math"])[:2],
                         ["-ffp-contract=fast", "-ffast-math"])
        self.assertIn("-Ofast", audit.gnu_problems(self.MODEL + ["-Ofast"]))
        self.assertEqual(audit.gnu_problems(["-ffast-math"] + self.MODEL), [])
        self.assertIn("-fassociative-math is not in the profile",
                      audit.gnu_problems(self.MODEL + ["-fassociative-math"]))
        self.assertIn("-fno-trapping-math is not in the profile",
                      audit.gnu_problems(self.MODEL + ["-fno-trapping-math"]))
        self.assertIn("-mfpmath=387 is a floating-point option this audit does not know",
                      audit.gnu_problems(self.MODEL + ["-mfpmath=387"]))

    def test_defaults_said_out_loud_are_fine(self):
        self.assertEqual(audit.gnu_problems(self.MODEL + ["-fmath-errno", "-ftrapping-math", "-mfpmath=sse"]), [])

    def test_fast_math_at_the_link_is_refused(self):
        self.assertEqual(len(audit.link_problems(["-O3", "-ffast-math"], "gnu")), 1)
        self.assertEqual(audit.link_problems(["-O3"], "gnu"), [])


class SourceSearch(unittest.TestCase):
    def _hits(self, name, text):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return [(pattern, audit.allowed_use(path, pattern, line))
                    for _, pattern, line in audit.scan_source(path)]

    def test_jolts_precise_on_and_pop_are_allowed(self):
        hits = self._hits("Jolt/Core/Core.h",
                          '#define JPH_PRECISE_MATH_ON __pragma(float_control(precise, on, push))\n'
                          '#define JPH_PRECISE_MATH_OFF __pragma(float_control(pop))\n')
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(why for _, why in hits))

    def test_precise_off_contraction_and_fast_math_in_a_source_are_refused(self):
        for text in ("#pragma float_control(precise, off)\n", "#pragma fp_contract(on)\n",
                     "#pragma STDC FP_CONTRACT ON\n", '#pragma GCC optimize("fast-math")\n',
                     "#pragma clang fp contract(fast)\n",
                     '__attribute__((optimize("fast-math"))) void f();\n',
                     "void f() { _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_ON); }\n",
                     "void f() { fesetround(FE_UPWARD); }\n",
                     "void f() { JPH::FPFlushDenormals flush; }\n"):
            hits = self._hits("src/thing.cpp", text)
            self.assertTrue(hits and all(why is None for _, why in hits), text)

    def test_a_pragma_that_only_makes_floating_point_stricter_is_allowed_anywhere(self):
        for text in ("__pragma(float_control(precise, on, push))\n", "#pragma float_control(pop)\n",
                     "#pragma fp_contract(off)\n", "#pragma STDC FP_CONTRACT OFF\n",
                     '#pragma GCC optimize("fp-contract=off")\n'):
            hits = self._hits("src/thing.hpp", text)
            self.assertTrue(hits and all(why for _, why in hits), text)

    def test_jolts_exception_masks_are_allowed_and_a_denormal_flush_is_not(self):
        allowed = self._hits("jolt/core/fpcontrolword.h", "void f() { _mm_setcsr((mPrevState & ~Mask) | Value); }\n")
        self.assertTrue(allowed and all(why for _, why in allowed))
        refused = self._hits("src/thing.cpp", "void f() { _mm_setcsr(_mm_getcsr() | 0x8040); }\n")
        self.assertTrue(refused and all(why is None for _, why in refused))

    def test_a_mention_in_a_comment_or_a_macro_name_is_not_a_use(self):
        self.assertEqual(self._hits("src/thing.cpp", "// we never call _mm_setcsr( here\n/* fp_contract */\n"
                                                     "#ifndef STBIR_DONT_CHANGE_FP_CONTRACT\n#endif\n"), [])

    def test_only_what_the_compiled_files_can_include_is_searched(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "inc" / "sub").mkdir(parents=True)
            (root / "a.cpp").write_text('#include "local.h"\n#include <sub/deep.h>\n', encoding="utf-8")
            (root / "local.h").write_text("#pragma once\n", encoding="utf-8")
            (root / "inc" / "sub" / "deep.h").write_text('#if 0\n#include "flush.h"\n#endif\n', encoding="utf-8")
            (root / "inc" / "sub" / "flush.h").write_text("void f() { _MM_SET_FLUSH_ZERO_MODE(1); }\n", encoding="utf-8")
            (root / "inc" / "unused.h").write_text("#pragma float_control(precise, off)\n", encoding="utf-8")
            files = {Path(f).name for f in audit.reachable_files([str(root / "a.cpp")], [str(root / "inc")])}
            # Conditions are not evaluated: flush.h is reached through an #if 0.
            self.assertEqual(files, {"a.cpp", "local.h", "deep.h", "flush.h"})


def fixture_settings():
    generator = os.environ.get("BANJO_FP_FIXTURE_GENERATOR")
    if not generator:
        generator = "Visual Studio 17 2022" if os.name == "nt" else ("Ninja" if shutil.which("ninja") else "Unix Makefiles")
    return generator, os.environ.get("BANJO_FP_FIXTURE_PLATFORM", ""), os.environ.get("BANJO_FP_FIXTURE_CXX", "")


def expected(config, family):
    """(target, file) that must be refused in one configuration."""
    # debug_only_safe is refused in Debug too. Its Debug-only safe option is
    # the model's own option again, and CMake drops a repeated option, keeping
    # the first: every configuration's command ends on the unsafe one.
    broken = {("plain_fast", "plain_fast.cpp"), ("shell_fast", "shell_fast.cpp"),
              ("genex_source", "genex_source.cpp"), ("one_fast_file", "fast_file.cpp"),
              ("debug_only_safe", "debug_only_safe.cpp")}
    if config == "Release":
        broken.add(("release_usage", "release_usage.cpp"))
    return broken


class Fixture(unittest.TestCase):
    """The fixture configured for real, and audited from what CMake generated."""

    @classmethod
    def setUpClass(cls):
        cls.generator, cls.platform, cls.cxx = fixture_settings()
        cls.required = os.environ.get("BANJO_FP_FIXTURE_REQUIRED") == "1"
        cls.temp = tempfile.mkdtemp(prefix="fp-audit-")
        cls.builds = {}
        multi = cls.generator.startswith("Visual Studio") or "Multi-Config" in cls.generator
        variants = [("configured", ["-DCMAKE_BUILD_TYPE=Release"] if not multi else [])]
        if not multi:
            variants.append(("no-build-type", []))
        for name, extra in variants:
            build = Path(cls.temp) / name
            command = ["cmake", "-S", str(ROOT / "tests" / "fp_model_audit"), "-B", str(build),
                       "-G", cls.generator, *extra]
            if cls.platform:
                command += ["-A", cls.platform]
            if cls.cxx:
                command += [f"-DCMAKE_CXX_COMPILER={cls.cxx}"]
            done = subprocess.run(command, capture_output=True, text=True)
            if done.returncode != 0:
                message = f"the fixture would not configure ({name}):\n{done.stdout}\n{done.stderr}"
                if cls.required:
                    raise RuntimeError(message)
                raise unittest.SkipTest(message)
            cls.builds[name] = build

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp, ignore_errors=True)

    def _audit(self, build):
        result = audit.audit(build, None, True)
        family = result["family"]
        found, crossed, pragma = {}, {}, []
        for v in result["violations"]:
            if v["configuration"] == "*":
                pragma.append(v)
                continue
            name = Path(v["file"]).name
            if v["target"].startswith("(") or "(in " in v["problem"]:
                crossed.setdefault(v["configuration"], set()).add(name)
            else:
                found.setdefault(v["configuration"], set()).add((v["target"], name))
        return result, family, found, crossed, pragma

    def test_exactly_the_broken_files_are_refused_in_each_configuration(self):
        for variant, build in self.builds.items():
            result, family, found, crossed, pragma = self._audit(build)
            self.assertTrue(result["configurations"], variant)
            for config, counts in result["configurations"].items():
                with self.subTest(variant=variant, config=config):
                    want = expected(config, family)
                    self.assertEqual(found.get(config, set()), want)
                    # The commands the build tool will run say the same.
                    self.assertEqual(crossed.get(config, set()), {f for _, f in want})
                    self.assertGreater(counts["commands_cross_checked"], 0)
                    self.assertEqual(counts["cxx_files"], 9)
            # And the file that asks for fast math in a pragma, whatever the configuration.
            self.assertTrue(pragma and all("fast_pragma.cpp:" in v["file"] for v in pragma), pragma)

    def test_an_unnamed_configuration_is_still_audited(self):
        if "no-build-type" not in self.builds:
            self.skipTest(f"{self.generator} has no configuration without a name")
        result, family, found, crossed, pragma = self._audit(self.builds["no-build-type"])
        self.assertEqual(list(result["configurations"]), [""])
        self.assertEqual(found[""], expected("", family))

    def test_the_environment_is_part_of_the_command(self):
        build = self.builds["configured"]
        family = audit.audit(build, None, True)["family"]
        name = {"msvc": "_CL_", "gnu": "CCC_OVERRIDE_OPTIONS"}[family]
        profile = (build / "banjo-fp-profile.json").read_text(encoding="utf-8")
        if family == "gnu" and '"compiler_id": "GNU"' in profile:
            self.skipTest("GCC reads no environment variable that edits its command line")
        saved = os.environ.get(name)
        os.environ[name] = "/fp:fast" if family == "msvc" else "+-ffast-math"
        try:
            result = audit.audit(build, None, True)
        finally:
            if saved is None:
                del os.environ[name]
            else:
                os.environ[name] = saved
        refused = {Path(v["file"]).name for v in result["violations"]}
        self.assertIn("keeps_the_model.cpp" if family == "msvc" else "*", refused)

    def test_the_command_line_tool_exits_1_and_says_why(self):
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "check-fp-model.py"),
                               "--build", str(self.builds["configured"]), "--all-configs"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("plain_fast.cpp", done.stdout)
        self.assertIn("FAILED", done.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
