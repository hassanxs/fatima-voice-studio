#!/usr/bin/env python3
"""Smoke test for the Linux compatibility layer (linux/compat.py).

compat.py patches parts of studio/ at runtime. If upstream renames or moves one of them, the patch stops working
without any error message. This test is there to notice that.

  static    every name compat.py replaces or relies on still exists in studio/ (read with ast, nothing is imported)
  runtime   apply() works, and the patched names are the ones the rest of studio/ really uses
  web       the web page is served with the Linux wording

It needs the packages from requirements-linux.txt, but no GPU, no llama-tts and no display (the tray test is
skipped without one). Everything it writes goes to a temporary folder, not to your home directory.

  .venv/bin/python linux/test_smoke.py
  .venv/bin/python -m pytest linux/test_smoke.py
"""
import ast
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent / "studio"

# What compat.py replaces or relies on: module -> names that must exist at the top level of studio/<module>.py
TARGETS = {
    "config": {"HOME", "DATA", "CONFIG_FILE", "VOICES", "MUSIC", "DEFAULTS", "ENGINES", "ENGINE_EXE", "WHISPER_EXE",
               "engine_dir", "installed_engines", "whisper_dir", "tool_dir",
               # _patch_s2: S2 Pro and Whisper on the graphics card from setup.sh's downloads
               "S2_EXE", "S2_RUNTIME", "s2_dir", "s2_engine", "WHISPER_GPU", "whisper_gpu_engine", "MODELS",
               "OMNI_EXE", "OMNI_RUNTIME", "omni_dir", "omni_build"},
    "hardware": {"_vendor", "_registry_gpus", "_ram_gb", "_cpu", "on_battery", "recommended_engine"},
    "autostart": {"enabled", "set_enabled", "python_console", "install_launchers"},
    "updater": {"Updater"},
    "trash": {"to_recycle_bin"},
    "winui": {"pick_folder"},
    "engine": {"subprocess"},  # compat swaps engine.subprocess for a Popen that is killed with the app
    "s2engine": {"subprocess"},  # the same for the S2 Pro server
    "omniengine": {"subprocess"},  # and the OmniVoice server
    "tray": {"copy", "Tray"},
    # app.py imports these by name (`from .updater import Updater`), so compat has to patch them *before* app is
    # imported. Renaming them or importing them differently would bypass the patch.
    "app": {"create_app", "Updater", "pick_folder"},
    # _patch_tools: system ffmpeg instead of the Windows download, no Windows whisper zip, no engine download
    "media": {"ffmpeg_exe", "ffmpeg_source"},
    "downloads": {"Downloads"},
}
CLASS_MEMBERS = {
    ("updater", "Updater"): {"watch", "check", "start"},
    ("tray", "Tray"): {"__init__"},
    ("downloads", "Downloads"): {"tools", "start_tool", "delete_tool", "start_engine", "_whisper_missing",
                                 "start", "whisper_gpu", "ensure_whisper_gpu"},
}
DEFAULT_KEYS = {"batches_dir", "exports_dir", "models_dir", "engine", "check_updates"}

# The llama-tts command line the app builds. setup.sh checks for a llama.cpp new enough to understand it
# (LLAMA_MIN_BUILD): if this set changes, that minimum may have to change too.
ENGINE_FLAGS = {"-m", "-mm", "-ngl", "-c", "4096", "-n", "-f", "--tts-lang", "-s", "--output", "--tts-speaker-file"}


def parse(module: str) -> ast.Module:
    return ast.parse((STUDIO / f"{module}.py").read_text(encoding="utf-8"), filename=f"studio/{module}.py")


def top_level_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    return names


class StaticChecks(unittest.TestCase):
    """Does what compat.py patches still exist upstream? Runs anywhere, imports nothing."""

    def test_patch_targets_exist(self):
        for module, wanted in TARGETS.items():
            with self.subTest(module=module):
                self.assertTrue((STUDIO / f"{module}.py").exists(), f"studio/{module}.py is gone")
                missing = wanted - top_level_names(parse(module))
                self.assertFalse(missing, f"studio/{module}.py no longer has {sorted(missing)}; compat.py patches them")

    def test_patched_class_members_exist(self):
        for (module, cls), wanted in CLASS_MEMBERS.items():
            with self.subTest(cls=f"{module}.{cls}"):
                node = next(n for n in parse(module).body if isinstance(n, ast.ClassDef) and n.name == cls)
                members = {n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                self.assertFalse(wanted - members, f"{module}.{cls} no longer has {sorted(wanted - members)}")

    def test_config_defaults_keys_exist(self):
        for node in parse("config").body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DEFAULTS" for t in node.targets):
                keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
                self.assertFalse(DEFAULT_KEYS - keys, f"config.DEFAULTS lost {sorted(DEFAULT_KEYS - keys)}")
                return
        self.fail("config.DEFAULTS not found")

    def test_web_script_patches_still_match(self):
        """compat.py edits/rewords studio/web/app.js; if upstream changes those lines the patch silently stops."""
        sys.path.insert(0, str(HERE))
        import compat
        js = (STUDIO / "web" / "app.js").read_text(encoding="utf-8")
        for old, _ in compat.JS_PATCHES + compat.TEXTS:
            with self.subTest(old=old[:50]):
                # TEXTS also holds strings from Python files (error messages); look in all of studio/
                found = old in js or any(old in f.read_text(encoding="utf-8") for f in STUDIO.glob("*.py"))
                self.assertTrue(found, f"“{old[:60]}…” is no longer in studio/; update compat.py")

    def test_engine_command_line(self):
        used = {n.value for n in ast.walk(parse("engine")) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(ENGINE_FLAGS - used,
                         f"engine.py no longer passes {sorted(ENGINE_FLAGS - used)} to llama-tts. "
                         "Check LLAMA_MIN_BUILD in setup.sh and the llama.cpp version in the README.")


@unittest.skipUnless(sys.platform.startswith("linux"), "the compatibility layer is for Linux")
class RuntimeChecks(unittest.TestCase):
    """apply() the patches, then check what the app really ends up using."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        # before compat is imported: it reads these when it loads
        os.environ.update(FVS_HOME=str(root / "home"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_MUSIC_DIR=str(root / "music"))
        sys.path.insert(0, str(HERE))
        import compat
        compat.apply()
        # imported only now, in the same order as run.py
        from studio import (app, autostart, config, engine, hardware, store, transcribe, updater, voices)
        cls.compat, cls.app, cls.autostart, cls.config, cls.engine = compat, app, autostart, config, engine
        cls.hardware, cls.store, cls.transcribe, cls.updater, cls.voices = hardware, store, transcribe, updater, voices

    def test_apply_twice_is_harmless(self):
        self.compat.apply()

    def test_paths_and_engine(self):
        home = Path(os.environ["FVS_HOME"])
        c = self.config
        self.assertEqual(c.ENGINE_EXE, "llama-tts")
        self.assertEqual(c.WHISPER_EXE, "whisper-cli")
        self.assertEqual(list(c.ENGINES), ["system"])
        self.assertEqual(c.DEFAULTS["engine"], "system")
        self.assertFalse(c.DEFAULTS["check_updates"])
        self.assertEqual(c.engine_dir({"engine": "system"}), home / "engine" / "system")
        self.assertEqual(c.DATA, home / "data")
        self.assertIsInstance(c.installed_engines({"engine": "system"}), list)

    def test_llama_build_is_read_from_every_known_version_format(self):
        script = Path(self.tmp.name) / "fake-llama-tts"
        old = os.environ.get("FVS_LLAMA_TTS")
        try:
            os.environ["FVS_LLAMA_TTS"] = str(script)
            for line, want in [("version: 0.3.0-dev (build 10689, commit c13e6fe)", "b10689"),
                               ("version: 10689 (c13e6fe)", "b10689"), ("version: b9000 (abc)", "b9000"),
                               ("no version here", None)]:
                script.write_text(f"#!/bin/sh\necho '{line}' >&2\n")
                script.chmod(0o755)
                self.assertEqual(self.compat.llama_build(), want, line)
            os.environ["FVS_LLAMA_TTS"] = str(script) + "-missing"
            self.assertIsNone(self.compat.llama_build())
        finally:
            if old is None:
                os.environ.pop("FVS_LLAMA_TTS", None)
            else:
                os.environ["FVS_LLAMA_TTS"] = old

    def test_about_page_does_not_show_the_windows_engine_pin(self):
        # studio/ pins the release of the Windows engine downloads; on Linux the installed build is shown instead
        self.assertEqual(self.config.ENGINE_RELEASE, self.compat.llama_build() or "not found")

    def test_patched_names_are_the_ones_in_use(self):
        for mod in (self.store, self.voices, self.transcribe):
            self.assertIs(mod.to_recycle_bin, self.compat._to_trash, f"{mod.__name__} still has the Windows trash")
        self.assertIs(self.app.pick_folder, self.compat._pick_folder)
        self.assertIs(self.app.Updater, self.updater.Updater)
        self.assertEqual(self.app.Updater.__name__, "LinuxUpdater", "app.py still has the Windows updater")

    def test_hardware(self):
        h = self.hardware
        self.assertIs(h._registry_gpus, self.compat._lspci_gpus)
        self.assertEqual(h.recommended_engine({}), "system")
        self.assertIsInstance(h._registry_gpus(), list)
        self.assertGreater(h._ram_gb(), 0)
        self.assertIsInstance(h._cpu(), str)
        self.assertIn(h.on_battery(), (None, True, False))

    def test_autostart(self):
        file = self.compat.AUTOSTART_FILE
        if not str(file).startswith(self.tmp.name):
            self.skipTest("compat was imported before the test set XDG_CONFIG_HOME; not touching the real one")
        a = self.autostart
        self.assertFalse(a.enabled())
        a.set_enabled(True)
        self.assertTrue(a.enabled())
        self.assertIn("fatima-voice-studio", file.read_text(encoding="utf-8"))
        a.set_enabled(False)
        self.assertFalse(a.enabled())

    def test_engine_is_tied_to_the_app(self):
        if not shutil.which("setpriv"):
            self.skipTest("setpriv (util-linux) not installed")
        self.assertIsNot(self.engine.subprocess.Popen, subprocess.Popen)
        p = self.engine.subprocess.Popen([sys.executable, "-c", "print('ok')"], stdout=subprocess.PIPE)
        self.assertEqual(p.communicate(timeout=30)[0].strip(), b"ok")
        self.assertEqual(p.returncode, 0)

    def test_progress_line_still_parsed(self):
        self.assertEqual(self.engine.DONE.search("generated 123 frames").group(1), "123")

    def test_updater_says_no(self):
        state = asyncio.run(self.app.Updater(self.config.load()).check())
        self.assertEqual(state["status"], "error")
        self.assertIn("git pull", state["error"])

    def test_web_page_has_linux_wording(self):
        from fastapi.testclient import TestClient
        raw = (STUDIO / "web" / "app.js").read_text(encoding="utf-8")
        served = TestClient(self.app.create_app(self.config.load())).get("/app.js")
        self.assertEqual(served.status_code, 200)
        for old, new in self.compat.TEXTS:
            if old in raw:
                self.assertNotIn(old, served.text, f"“{old}” is still shown")
                self.assertIn(new, served.text)

    # ---- ffmpeg, whisper, system engine, paths with spaces -------------------------------------------------

    def _client(self):
        from fastapi.testclient import TestClient
        return TestClient(self.app.create_app(self.config.load()), headers={"X-Studio": "1"})  # POSTs need the header

    def test_ffmpeg_is_the_system_one_never_a_windows_exe(self):
        from studio import media
        fake_exe = self.config.tool_dir("ffmpeg") / "ffmpeg.exe"  # what a Windows download would leave behind
        fake_exe.parent.mkdir(parents=True, exist_ok=True)
        fake_exe.write_text("MZ not a Linux program")
        self.addCleanup(fake_exe.unlink, missing_ok=True)
        with tempfile.TemporaryDirectory() as bindir:
            real = Path(bindir) / "ffmpeg"
            real.write_text("#!/bin/sh\n")
            real.chmod(0o755)
            old_path = os.environ["PATH"]
            os.environ["PATH"] = bindir
            try:
                self.assertEqual(media.ffmpeg_exe(), str(real), "ffmpeg.exe must not win over the system ffmpeg")
                self.assertEqual(media.ffmpeg_source(), "system")
            finally:
                os.environ["PATH"] = old_path
            os.environ["PATH"] = bindir + "/nothing-here"
            try:
                self.assertIsNone(media.ffmpeg_exe(), "ffmpeg.exe must not be used when there is no system ffmpeg")
                self.assertIsNone(media.ffmpeg_source())
            finally:
                os.environ["PATH"] = old_path

    def test_no_windows_ffmpeg_download_is_offered_or_started(self):
        c = self._client()
        tools = c.get("/api/tools").json()
        self.assertEqual([t["key"] for t in tools], ["ffmpeg"])
        self.assertTrue(tools[0]["system_only"])
        self.assertEqual(tools[0]["size"], 0)
        self.assertFalse(tools[0]["installed"])
        self.assertFalse(any("zip" in t for t in tools))
        r = c.post("/api/tools/ffmpeg/download")
        self.assertEqual(r.status_code, 409)
        self.assertIn("ffmpeg", r.json()["detail"])
        self.assertIsNone(c.get("/api/tools").json()[0]["job"], "no download job may have been started")
        self.assertFalse((self.config.tool_dir("ffmpeg") / "ffmpeg.exe").exists())
        self.assertNotIn("github.com/GyanD", str(self.config.TOOLS))

    def test_missing_ffmpeg_message_points_to_the_package_manager(self):
        old_path, os.environ["PATH"] = os.environ["PATH"], "/nonexistent"
        try:
            r = self._client().post("/api/transcripts", files={"file": ("clip.mp4", b"x", "video/mp4")})
        finally:
            os.environ["PATH"] = old_path
        # without a Whisper model the request stops earlier; either way the Models-page advice must not appear
        self.assertNotIn("Models page (Tools)", r.text)

    def test_system_engine_has_no_download(self):
        c = self._client()
        eng = next(e for e in c.get("/api/setup").json()["engines"] if e["key"] == "system")
        self.assertEqual(eng["size"], 0)
        r = c.post("/api/setup/engines/system/download")
        self.assertEqual(r.status_code, 409)
        self.assertIn("nothing to download", r.json()["detail"])
        self.assertIsNone(c.get("/api/setup").json()["engines"][0]["job"])

    def test_page_script_has_no_download_button_for_system_things(self):
        js = self._client().get("/app.js").text
        self.assertIn("t.system_only", js)
        self.assertIn("else if (!e.size)", js)
        self.assertNotIn("get ffmpeg on the", js)

    def test_whisper_model_download_skips_the_windows_zip(self):
        from studio import downloads
        d = downloads.Downloads(self.config.load())
        self.assertFalse(d._whisper_missing(), "the whisper-bin-x64.zip must never be requested on Linux")
        for m in d.status():
            if m["kind"] == "subtitles":
                self.assertEqual(m["to_download"], sum(self.config.FILES[f][1] for f in self.config.model_files(m["key"])))
                self.assertIn("build-whisper.sh", m["about"])

    def test_missing_whisper_cli_gets_a_clear_warning(self):
        cfg = self.config.load()
        folder = Path(cfg["models_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        model = folder / self.config.MODELS["whisper-base"]["files"][0]
        model.write_bytes(b"x")
        self.addCleanup(model.unlink, missing_ok=True)
        old = os.environ.get("FVS_WHISPER_CLI")
        os.environ["FVS_WHISPER_CLI"] = "/nonexistent/whisper-cli"
        try:
            hw = self.hardware.detect(True)
            msgs = [w["message"] for w in self.hardware.warnings(hw, cfg, "system")]
        finally:
            if old is None:
                del os.environ["FVS_WHISPER_CLI"]
            else:
                os.environ["FVS_WHISPER_CLI"] = old
        self.assertTrue(any("./build-whisper.sh" in m for m in msgs), msgs)

    def test_desktop_entry_quotes_paths_with_spaces(self):
        c = self.compat
        self.assertEqual(c.exec_quote("/opt/fvs/launcher"), "/opt/fvs/launcher")
        self.assertEqual(c.exec_quote("/home/me/My Apps/fvs"), '"/home/me/My Apps/fvs"')
        self.assertEqual(c.exec_quote("/a b/$x"), '"/a b/\\\\$x"')
        self.assertEqual(c.exec_quote("/100%/x y"), '"/100%%/x y"')
        line = next(l for l in c.desktop_entry("--no-browser").splitlines() if l.startswith("Exec="))
        self.assertTrue(line.endswith(" --no-browser"))
        if " " in str(c.LINUX_DIR):
            self.assertTrue(line.startswith('Exec="'), line)

    def test_tray_patch(self):
        try:
            import pystray  # noqa: F401  (needs a display or AppIndicator to import)
        except Exception as e:
            self.skipTest(f"no tray backend here: {type(e).__name__}")
        from studio import tray
        self.compat.patch_tray()
        self.assertIs(tray.copy, self.compat._copy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
