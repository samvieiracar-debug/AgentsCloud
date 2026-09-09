"""Integração das novas escolhas com Git e perfis pessoais descartáveis."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from agentscloud.cli import main
from agentscloud.diagnostics import Diagnostics
from agentscloud.git import Repository
from agentscloud.prepared import PreparedCheckout
from agentscloud.processes import EventLog, process_output, run_command
import test_agentscloud as existing
from test_agentscloud import FakeUI, agent_bytes


class HubChoices(FakeUI):
    def __init__(self, *args, files=(), reviews=(), on_choose=None, on_review=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.files = files
        self.reviews = iter(reviews)
        self.reviewed = []
        self.offered = []
        self.categories = {}
        self.on_choose = on_choose
        self.on_review = on_review

    def choose_installation(self, agents, categories):
        self.offered = agents
        self.categories = categories
        if self.on_choose:
            self.on_choose()
        return self.files

    def review_step(self, title, content):
        self.reviewed.append((title, content))
        self.emit(content)
        if self.on_review:
            self.on_review(title)
        return next(self.reviews)


@unittest.skipUnless(shutil.which("git"), "Git não disponível")
class HubFlowTests(unittest.TestCase):
    # Reutiliza apenas a montagem do laboratório; não duplica testes herdados.
    setUp = existing.GitFlowTests.setUp
    git = existing.GitFlowTests.git
    identity = existing.GitFlowTests.identity
    head = existing.GitFlowTests.head
    command = existing.GitFlowTests.command
    publish = existing.GitFlowTests.publish
    personal_agent = existing.GitFlowTests.personal_agent
    assert_clean = existing.GitFlowTests.assert_clean

    def test_selection_uses_synced_catalog_and_installs_only_chosen_bytes(self):
        self.publish()
        ui = HubChoices(confirms=[True, True], files=["new.toml"])
        self.command("update", ui)
        self.assertEqual({a.file for a in ui.offered}, {"base.toml", "new.toml"})
        self.assertEqual(ui.categories["new.toml"], "Qualidade")
        folder = self.personal / "agents"
        self.assertEqual([p.name for p in folder.iterdir()], ["new.toml"])
        self.assertEqual((folder / "new.toml").read_bytes(), (self.seed / "Agents/new.toml").read_bytes())
        self.assertIn("instalar 1 agente(s)", ui.prompts[-1])
        self.assert_clean()

    def test_empty_selection_does_not_create_personal_folder_or_confirm(self):
        ui = HubChoices(files=[])
        self.command("update", ui)
        self.assertFalse(self.personal.exists())
        self.assertEqual(ui.prompts, [])
        self.assertIn("Nenhum agente selecionado", ui.output)

    def test_invalid_selection_cannot_install_unknown_or_duplicate_agents(self):
        for files in (["missing.toml"], ["base.toml", "base.toml"], "base.toml", [None]):
            with self.subTest(files=files):
                ui = HubChoices(files=files)
                self.command("update", ui, expected=1)
                self.assertFalse(self.personal.exists())
                self.assertIn("Seleção inválida", ui.output)
                self.assertEqual(ui.prompts, [])

    def test_selected_conflict_can_be_preserved_without_backup(self):
        personal = self.personal_agent("base.toml", "base")
        before = personal.read_bytes()
        ui = HubChoices(confirms=[True, False], files=["base.toml"])
        self.command("update", ui)
        self.assertEqual(personal.read_bytes(), before)
        self.assertEqual(list(personal.parent.glob("*.bak-*")), [])
        self.assertIn("Preservado por escolha", ui.output)

    def test_prepared_checkout_rechecks_upstream_after_selection(self):
        repo = Repository(self.clone)
        upstream = repo.fetch_upstream()
        prepared = PreparedCheckout(repo.head(), repo.branch(), upstream.remote, upstream.branch_ref)
        ui = HubChoices(confirms=[True], files=["base.toml"], on_choose=self.publish)
        result = main(["update", "--repo", str(self.clone)], ui=ui, prepared=prepared)
        self.assertEqual(result, 1, ui.output)
        self.assertIn("upstream mudou", ui.output)
        self.assertFalse(self.personal.exists())

    def test_declining_either_review_stage_never_copies_or_commits(self):
        source = self.personal_agent()
        for decisions in ([False], [True, False]):
            with self.subTest(decisions=decisions):
                ui = HubChoices(confirms=[False], texts=[str(source), "Equipe", ""], reviews=decisions)
                self.command("upload", ui)
                self.assertEqual(len(ui.reviewed), len(decisions))
                self.assertIn("Upload recusado", ui.output)
                self.assertEqual(self.head(self.clone), self.initial)
                self.assertFalse((self.clone / "Agents/mine.toml").exists())
                self.assert_clean()

    def test_reviewed_source_change_stops_before_copy(self):
        source = self.personal_agent()

        def change_source(title):
            if title.startswith("2/3"):
                source.write_bytes(agent_bytes("mine", "Mudou durante a revisão"))

        ui = HubChoices(confirms=[False, True], texts=[str(source), "Equipe", ""],
                        reviews=[True, True], on_review=change_source)
        self.command("upload", ui, expected=1)
        self.assertIn("origem mudou", ui.output)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertFalse((self.clone / "Agents/mine.toml").exists())
        self.assert_clean()

    def test_review_stages_publish_exact_original_file_after_final_confirmation(self):
        source = self.personal_agent()
        original = source.read_bytes()
        ui = HubChoices(confirms=[False, True], texts=[str(source), "Equipe", "Equipe de teste"],
                        reviews=[True, True])
        self.command("upload", ui)
        self.assertEqual([title[:3] for title, _ in ui.reviewed], ["1/3", "2/3"])
        self.assertIn("Responsável: Equipe de teste", ui.reviewed[0][1])
        self.assertIn(original.decode("utf-8"), ui.reviewed[1][1])
        self.assertIn("executar git push", ui.prompts[-1])
        self.assertIn("3/3", ui.prompts[-1])
        self.assertIn("refs/heads/equipe", ui.prompts[-1])
        self.assertEqual((self.clone / "Agents/mine.toml").read_bytes(), original)
        remote_head = self.git(self.bare, "rev-parse", "refs/heads/equipe").decode().strip()
        self.assertEqual(self.head(self.clone), remote_head)
        self.assert_clean()

    def test_diagnostic_repair_requires_callback_approval_of_exact_action(self):
        self.git(self.clone, "config", "--unset", "user.name")
        actions = []

        def refuse(description):
            actions.append(description)
            return False

        doctor = Diagnostics(self.clone, offline=True, confirm_fn=refuse)
        doctor.collect()
        self.assertFalse(doctor.repairs(input_fn=lambda _: "Nome de teste", emit=lambda _: None))
        missing = doctor.git("config", "--get", "user.name")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(len(actions), 1)
        self.assertIn("Gravar user.name=Nome de teste", actions[0])
        self.assertIn(str(doctor.git_config_path), actions[0])

        doctor.confirm_fn = lambda description: description == actions[0]
        self.assertTrue(doctor.repairs(input_fn=lambda _: "Nome de teste", emit=lambda _: None))
        self.assertEqual(self.git(self.clone, "config", "--get", "user.name").decode().strip(), "Nome de teste")


class HubProcessOutputTests(unittest.TestCase):
    def test_streaming_is_scoped_sanitized_and_does_not_capture_global_output(self):
        messages = []
        console = io.StringIO()
        script = "import sys; print('token=SECRET_SENTINEL'); print('falha visível', file=sys.stderr)"
        with redirect_stdout(console), redirect_stderr(console):
            with process_output(messages.append):
                result = run_command([sys.executable, "-I", "-X", "utf8", "-c", script], interactive=True)
            run_command([sys.executable, "-I", "-c", "print('fora do hub')"], interactive=True)
        self.assertEqual(result.returncode, 0)
        shown = "".join(messages)
        self.assertNotIn("SECRET_SENTINEL", shown)
        self.assertIn("[omitido]", shown)
        self.assertIn("falha visível", shown)
        self.assertEqual(console.getvalue().strip(), "fora do hub")

    def test_hub_subprocess_cannot_read_keyboard_or_request_login(self):
        script = ("import json, os, sys; print(json.dumps([sys.stdin.read(), "
                  "os.environ.get('GIT_TERMINAL_PROMPT'), os.environ.get('GCM_INTERACTIVE')]))")
        with process_output(lambda _: None):
            result = run_command([sys.executable, "-I", "-c", script], interactive=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), ["", "0", "never"])

    def test_event_log_failure_uses_hub_output_and_context_restores_after_error(self):
        messages = []
        with tempfile.TemporaryDirectory() as folder:
            blocker = Path(folder) / "file"
            blocker.write_text("not a directory", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "intentional"):
                with process_output(messages.append):
                    self.assertFalse(EventLog(blocker).write("test"))
                    raise RuntimeError("intentional")
            console = io.StringIO()
            with redirect_stderr(console):
                self.assertFalse(EventLog(blocker).write("outside"))
            self.assertIn("Aviso", console.getvalue())
        self.assertEqual(len(messages), 1)
        self.assertIn("Aviso", messages[0])


if __name__ == "__main__":
    unittest.main()
