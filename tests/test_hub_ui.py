"""Interações reais da TUI, sem rede, instalação ou publicação de agentes."""

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from textual.widgets import Button, RichLog, Select, SelectionList

from agentscloud.agents import Agent
from agentscloud.hub import AgentPicker, HubApp, Prompt, run_hub
from agentscloud.ui import TerminalUI


class HubUITests(unittest.IsolatedAsyncioTestCase):
    async def wait_until(self, pilot, predicate):
        for _ in range(100):
            await pilot.pause(0.02)
            if predicate():
                return
        self.fail("A interface não chegou ao estado esperado.")

    async def test_launch_resize_and_navigation_never_start_operation(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            app = HubApp(Path(directory), runner=lambda *args: calls.append(args) or 0)
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.press("f3")
                self.assertEqual(app.current_action, "upload")
                await pilot.resize_terminal(80, 24)
                await self.wait_until(pilot, lambda: not app.query_one("#session-log", RichLog).show_horizontal_scrollbar)
                self.assertTrue(app.screen.has_class("compact"))
                self.assertFalse(app.screen.has_class("too-small"))
                self.assertTrue(app.query_one("#start", Button).region.bottom <= 24)
                self.assertFalse(app.query_one("#session-log", RichLog).show_horizontal_scrollbar)
                await pilot.resize_terminal(79, 23)
                self.assertTrue(app.screen.has_class("too-small"))
                await pilot.resize_terminal(120, 36)
                self.assertFalse(app.screen.has_class("too-small"))
                await pilot.press("f4")
                self.assertEqual(app.current_action, "diagnostico")
                self.assertEqual(calls, [])

    async def test_confirmation_defaults_to_no(self):
        answers = []
        def runner(action, root, ui):
            answers.append(ui.confirm("Publicar contribuição?"))
            return 0
        with tempfile.TemporaryDirectory() as directory:
            app = HubApp(Path(directory), runner=runner)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.click("#start")
                await self.wait_until(pilot, lambda: app.pending_dialog is not None)
                await pilot.press("enter")
                await self.wait_until(pilot, lambda: not app.busy)
                self.assertEqual(answers, [False])

    async def test_text_review_selection_bridge(self):
        answers = []
        def runner(action, root, ui):
            answers.append(ui.text("Categoria:"))
            answers.append(ui.select("Agente:", [("Primeiro", "a"), ("Segundo", "b")]))
            answers.append(ui.review_step("2/3 Conteúdo TOML", 'name = "[red]literal[/red]"\n' * 100))
            return 0
        with tempfile.TemporaryDirectory() as directory:
            app = HubApp(Path(directory), runner=runner)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.click("#start")
                await self.wait_until(pilot, lambda: app.pending_dialog is not None)
                await pilot.press("a", "1", "2", "3", "enter")
                await self.wait_until(pilot, lambda: isinstance(app.pending_dialog, Prompt) and app.pending_dialog.kind == "select")
                await pilot.press("down", "enter")
                await self.wait_until(pilot, lambda: isinstance(app.pending_dialog, Prompt) and app.pending_dialog.kind == "review")
                self.assertGreater(len(app.screen.query_one("#review-content", RichLog).lines), 50)
                await pilot.press("pagedown")
                await pilot.click("#accept")
                await self.wait_until(pilot, lambda: not app.busy)
                self.assertEqual(answers, ["a123", "b", True])

    async def test_filter_preserves_selected_agents_and_clear_removes_hidden(self):
        agents = [Agent("a.toml", "alpha", "Descrição acentuada " * 20, b"a"),
                  Agent("b.toml", "beta", "Segunda especialidade", b"b")]
        with tempfile.TemporaryDirectory() as directory:
            app = HubApp(Path(directory))
            async with app.run_test(size=(80, 24)) as pilot:
                picker = AgentPicker(agents, {"a.toml": "Design", "b.toml": "Código"})
                app.push_screen(picker)
                await pilot.pause()
                category = picker.query_one("#category", Select)
                category.value = "Design"
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(picker.chosen, {"a.toml"})
                category.value = "Código"
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(picker.chosen, {"a.toml", "b.toml"})
                category.value = "Design"
                await pilot.pause()
                self.assertEqual(picker.query_one("#agent-list", SelectionList).selected, ["a.toml"])
                self.assertTrue(picker.query_one("#agent-list", SelectionList).render_line(0).text.startswith("[x]"))
                self.assertTrue(picker.query_one("#use-selection", Button).region.bottom <= 24)
                await pilot.click("#clear-selection")
                await pilot.pause()
                self.assertEqual(picker.chosen, set())
                self.assertTrue(picker.query_one("#use-selection", Button).disabled)

    async def test_installation_entire_catalog_or_individual_choice(self):
        agents = [Agent("a.toml", "alpha", "Primeiro", b"a"), Agent("b.toml", "beta", "Segundo", b"b")]
        results = []
        def runner(action, root, ui):
            results.append(ui.choose_installation(agents, {"a.toml": "Design", "b.toml": "Código"}))
            return 0
        with tempfile.TemporaryDirectory() as directory:
            app = HubApp(Path(directory), runner=runner)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.click("#start")
                await self.wait_until(pilot, lambda: app.pending_dialog is not None)
                await pilot.press("enter")
                await self.wait_until(pilot, lambda: not app.busy)
                self.assertEqual(results, [["a.toml", "b.toml"]])
                await pilot.click("#start")
                await self.wait_until(pilot, lambda: app.pending_dialog is not None)
                await pilot.press("down", "enter")
                await self.wait_until(pilot, lambda: isinstance(app.pending_dialog, AgentPicker) and app.focused is not None and app.focused.id == "agent-list")
                await pilot.press("space")
                await self.wait_until(pilot, lambda: not app.screen.query_one("#use-selection", Button).disabled)
                await pilot.click("#use-selection")
                await self.wait_until(pilot, lambda: not app.busy)
                self.assertEqual(results[-1], ["a.toml"])

    async def test_pending_operation_cancel_waits_for_checkpoint(self):
        release = threading.Event()
        began = threading.Event()
        def runner(action, root, ui):
            began.set()
            release.wait(5)
            ui.confirm("Próxima alteração?")
            self.fail("Uma confirmação não pode ser concedida após cancelar.")
        with tempfile.TemporaryDirectory() as directory:
            app = HubApp(Path(directory), runner=runner)
            async with app.run_test(size=(120, 36)) as pilot:
                try:
                    await pilot.click("#start")
                    await self.wait_until(pilot, began.is_set)
                    await pilot.press("escape")
                    self.assertTrue(app.busy)
                    self.assertTrue(app.cancel_requested.is_set())
                    release.set()
                    await self.wait_until(pilot, lambda: not app.busy)
                    self.assertEqual(app.last_code, 130)
                    self.assertIsNone(app.pending_dialog)
                finally:
                    release.set()

    async def test_escape_cancels_prompt_and_error_restores_navigation(self):
        def runner(action, root, ui):
            ui.text("Caminho:")
            return 0
        with tempfile.TemporaryDirectory() as directory:
            app = HubApp(Path(directory), runner=runner)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.click("#start")
                await self.wait_until(pilot, lambda: app.pending_dialog is not None)
                await pilot.press("escape")
                await self.wait_until(pilot, lambda: not app.busy)
                self.assertEqual(app.last_code, 130)
                self.assertFalse(app.query_one("#nav-upload", Button).disabled)
                def failure(*args):
                    raise OSError("Falha de exemplo")
                app.runner = failure
                await pilot.click("#start")
                await self.wait_until(pilot, lambda: not app.busy)
                self.assertEqual(app.last_code, 1)
                self.assertFalse(app.query_one("#start", Button).disabled)


class HubEntryTests(unittest.TestCase):
    def test_redirected_output_does_not_start_tui(self):
        with patch("agentscloud.hub.sys.stdin.isatty", return_value=False), patch("agentscloud.hub.HubApp") as app:
            self.assertEqual(run_hub(Path.cwd()), 2)
            app.assert_not_called()

    def test_legacy_terminal_preserves_choices_between_categories(self):
        agents = [Agent("a.toml", "alpha", "Primeiro", b"a"), Agent("b.toml", "beta", "Segundo", b"b")]
        ui = TerminalUI()
        with patch.object(ui, "select", side_effect=["choose", "Design", "filter", "Código", "continue"]), \
                patch("agentscloud.ui.questionary.checkbox") as checkbox:
            checkbox.return_value.unsafe_ask.side_effect = [["a.toml"], ["b.toml"]]
            self.assertEqual(ui.choose_installation(agents, {"a.toml": "Design", "b.toml": "Código"}), ["a.toml", "b.toml"])


if __name__ == "__main__":
    unittest.main()
