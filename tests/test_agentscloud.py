"""Testes de comportamento com remotos Git e diretórios pessoais descartáveis."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agentscloud.agents import check_unique, parse_agent, read_agent, validate_filename
from agentscloud.catalog import (
    Bundle, END, START, load_bundle, make_bundle, parse_catalog, render_index,
    serialize_catalog, updated_readme, valid_category, valid_maintainer,
)
from agentscloud.cli import main
from agentscloud.errors import AgentsCloudError, Cancelled
from agentscloud.install import codex_home, install_agents, scan_personal


def agent_bytes(name="base", description="Descrição original.", extra=""):
    return (f'name = {json.dumps(name)}\n'
            f'description = {json.dumps(description, ensure_ascii=False)}\n'
            'developer_instructions = """\nLeia o contexto e entregue evidências.\n"""\n'
            + extra).encode("utf-8")



def legacy_readme(category="Desenvolvimento"):
    """Texto literal do índice antigo; não usa o renderizador como oráculo."""
    return f"""# Catálogo legado

{START}

### {category}

| Nome | Sintaxe | Categoria | Descrição |
| --- | --- | --- | --- |
| [base](Agents/base.toml) | Use o agente base para … | {category} | Descrição original. |

{END}

Rodapé legado.
""".encode("utf-8")


def write_bundle(root, agents, categories=None, maintainers=None):
    folder = root / "Agents"
    folder.mkdir(exist_ok=True)
    categories = categories or {name: "Desenvolvimento" for name in agents}
    for filename, content in agents.items():
        (folder / filename).write_bytes(content)
    (root / "catalog.toml").write_bytes(serialize_catalog(categories, maintainers))
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(f"# Equipe\n\n{START}\n\n{END}\n\nRodapé preservado.\n", encoding="utf-8", newline="\n")
    readme.write_bytes(updated_readme(readme.read_bytes(), load_bundle(root)))


class FakeUI:
    def __init__(self, confirms=(), texts=(), selected=None, on_confirm=None):
        self.confirms = iter(confirms)
        self.texts = iter(texts)
        self.selected = selected
        self.on_confirm = on_confirm
        self.messages = []
        self.prompts = []
        self.choices = []

    def emit(self, message):
        self.messages.append(message)

    def confirm(self, message):
        self.prompts.append(message)
        if self.on_confirm:
            self.on_confirm(message)
        return next(self.confirms)

    def text(self, message):
        self.prompts.append(message)
        answer = next(self.texts)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def select(self, message, choices):
        self.choices = choices
        if isinstance(self.selected, BaseException):
            raise self.selected
        return self.selected or choices[0][1]

    @property
    def output(self):
        return "\n".join(self.messages)


class ValidationTests(unittest.TestCase):
    def test_identity_independent_of_filename_and_optional_config_preserved(self):
        raw = agent_bytes("meu-agente", extra='# Opções mantidas literalmente.\nmodel = "exemplo"\n')
        agent = parse_agent("outro_arquivo.toml", raw)
        self.assertEqual(agent.name, "meu-agente")
        self.assertEqual(agent.content, raw)

    def test_required_fields_and_invalid_toml(self):
        for bad in (b'not = [', b'\xff', b'name = "ok"\n',
                    agent_bytes().replace(b'description = ', b'description = 42 # '),
                    agent_bytes().replace(b'name = "base"', b'name = ""')):
            with self.subTest(bad=bad), self.assertRaises(AgentsCloudError):
                parse_agent("test.toml", bad)

    def test_portable_paths_and_casefold_identity(self):
        for filename in ("../x.toml", "a/b.toml", "a\\b.toml", "CON.toml", "x.txt", "-x.toml"):
            with self.subTest(filename=filename), self.assertRaises(AgentsCloudError):
                validate_filename(filename)
        for pair in ([parse_agent("x.toml", agent_bytes("Name")), parse_agent("y.toml", agent_bytes("name"))],
                     [parse_agent("X.toml", agent_bytes("a")), parse_agent("x.toml", agent_bytes("b"))]):
            with self.assertRaisesRegex(AgentsCloudError, "Esse nome está indisponível"):
                check_unique(pair)

    def test_catalog_roundtrip_and_invalid_category(self):
        values = {"b.toml": 'Revisão "geral" \\ categoria', "a.toml": "Qualidade"}
        serialized = serialize_catalog(values)
        self.assertEqual(parse_catalog(serialized).categories, values)
        self.assertLess(serialized.index(b"a.toml"), serialized.index(b"b.toml"))
        for category in ("", " x ", "x\nx", "x\x7f"):
            with self.subTest(category=category), self.assertRaises(AgentsCloudError):
                valid_category(category)

    def test_catalog_requires_exact_files_and_metadata(self):
        with self.assertRaisesRegex(AgentsCloudError, "inconsistente"):
            make_bundle({"base.toml": agent_bytes()}, serialize_catalog({"missing.toml": "Teste"}))
        with self.assertRaises(AgentsCloudError):
            parse_catalog(b'[[agents]]\nfile = "x.toml"\ncategory = "T"\nname = "extra"\n')

    def test_index_preserves_surrounding_content_escapes_and_crlf(self):
        bundle = Bundle([parse_agent("base.toml", agent_bytes(description="A | B\n<script>"))],
                        {"base.toml": "Qualidade"})
        initial = f"Introdução intacta.\r\n{START}\r\nvelho\r\n{END}\r\nRodapé.\r\n".encode()
        result = updated_readme(initial, bundle)
        self.assertTrue(result.startswith(b"Introdu\xc3\xa7\xc3\xa3o intacta.\r\n"))
        self.assertTrue(result.endswith(b"Rodap\xc3\xa9.\r\n"))
        self.assertIn(b"A &#124; B &lt;script&gt;", result)
        self.assertIn(b"Use o agente base", result)
        self.assertNotIn(b"\n", result.replace(b"\r\n", b""))
        self.assertEqual(updated_readme(result, bundle), result)
        with self.assertRaises(AgentsCloudError):
            updated_readme(b"sem marcadores", bundle)


    def test_legacy_catalog_without_maintainer_remains_valid(self):
        old = b'[[agents]]\nfile = "base.toml"\ncategory = "Teste"\n'
        catalog = parse_catalog(old)
        self.assertEqual(catalog.categories, {"base.toml": "Teste"})
        self.assertEqual(catalog.maintainers, {})
        self.assertEqual(serialize_catalog(catalog.categories, catalog.maintainers), old)
        bundle = make_bundle({"base.toml": agent_bytes()}, old)
        self.assertEqual(bundle.maintainers, {})
        legacy = legacy_readme("Teste")
        self.assertEqual(updated_readme(legacy, bundle), legacy)
        self.assertNotIn("Responsável", render_index(bundle))

    def test_maintainer_roundtrip_preserves_mixed_entries_and_native_toml(self):
        categories = {"base.toml": "Teste", "other.toml": "Qualidade"}
        maintainers = {"base.toml": 'Equipe "Revisão" | API'}
        catalog = parse_catalog(serialize_catalog(categories, maintainers))
        self.assertEqual(catalog.categories, categories)
        self.assertEqual(catalog.maintainers, maintainers)
        raw = agent_bytes(extra='model = "opcional"\n# Preservar este comentário.\n')
        bundle = make_bundle({"base.toml": raw, "other.toml": agent_bytes("other")},
                             serialize_catalog(catalog.categories, catalog.maintainers))
        self.assertEqual(bundle.agents[0].content, raw)
        index = render_index(bundle)
        self.assertIn('Equipe "Revisão" &#124; API', index)
        self.assertIn("Não informado", index)
        self.assertNotIn("maintainer", raw.decode())

    def test_invalid_maintainer_and_unknown_fields_rejected(self):
        base = b'[[agents]]\nfile = "base.toml"\ncategory = "Teste"\n'
        for value in ('""', "false", "123", "[]", '" Nome "', '"A\\nB"', '"A\\u007fB"', '"A\\u2028B"'):
            with self.subTest(value=value), self.assertRaises(AgentsCloudError):
                parse_catalog(base + f"maintainer = {value}\n".encode())
        with self.assertRaises(AgentsCloudError):
            parse_catalog(base + b'maintainer = "Equipe"\nowner = "Extra"\n')
        with self.assertRaises(AgentsCloudError):
            serialize_catalog({"base.toml": "Teste"}, {"missing.toml": "Equipe"})


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentscloud-install-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.personal = self.root / "personal"
        self.agent = parse_agent("base.toml", agent_bytes())

    def test_codex_home_default_override_and_empty(self):
        self.assertEqual(codex_home({}, self.root), self.root / ".codex")
        self.assertEqual(codex_home({"CODEX_HOME": str(self.personal)}, self.root), self.personal)
        with self.assertRaises(AgentsCloudError):
            codex_home({"CODEX_HOME": ""}, self.root)

    def test_install_idempotent_preserves_bytes_and_mtime(self):
        ui = FakeUI()
        stats = install_agents([self.agent], self.personal, ui.confirm, ui.emit)
        path = self.personal / "agents/base.toml"
        before = path.stat().st_mtime_ns
        self.assertEqual(stats["installed"], 1)
        self.assertEqual(path.read_bytes(), self.agent.content)
        stats = install_agents([self.agent], self.personal, ui.confirm, ui.emit)
        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(list(path.parent.glob("*.bak-*")), [])

    def test_conflict_refused_preserves_personal_file(self):
        older = parse_agent("base.toml", agent_bytes(description="Pessoal"))
        install_agents([older], self.personal, lambda _: False, lambda _: None)
        stats = install_agents([self.agent], self.personal, lambda _: False, lambda _: None)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual((self.personal / "agents/base.toml").read_bytes(), older.content)

    def test_same_identity_other_filename_replaced_with_backup(self):
        older = parse_agent("meu-arquivo.toml", agent_bytes("BASE", "Pessoal"))
        install_agents([older], self.personal, lambda _: False, lambda _: None)
        install_agents([self.agent], self.personal, lambda _: True, lambda _: None)
        folder = self.personal / "agents"
        self.assertFalse((folder / older.file).exists())
        self.assertEqual((folder / self.agent.file).read_bytes(), self.agent.content)
        backups = list(folder.glob("*.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), older.content)

    def test_crossed_name_and_file_conflicts_back_up_both(self):
        old = [parse_agent("base.toml", agent_bytes("outro")),
               parse_agent("outro.toml", agent_bytes("base"))]
        install_agents(old, self.personal, lambda _: False, lambda _: None)
        install_agents([self.agent], self.personal, lambda _: True, lambda _: None)
        folder = self.personal / "agents"
        self.assertEqual([p.name for p in folder.glob("*.toml")], ["base.toml"])
        self.assertEqual({p.read_bytes() for p in folder.glob("*.bak-*")}, {a.content for a in old})

    def test_scan_lists_new_ignores_invalid_occupied_and_duplicate_personal(self):
        folder = self.personal / "agents"
        folder.mkdir(parents=True)
        for filename, content in {
            "new.toml": agent_bytes("new"),
            "occupied.toml": agent_bytes("BASE"),
            "bad.toml": b"bad = [",
            "dup-a.toml": agent_bytes("dup"),
            "dup-b.toml": agent_bytes("DUP"),
        }.items():
            (folder / filename).write_bytes(content)
        scan = scan_personal(self.personal, [self.agent])
        self.assertEqual([a.file for a in scan.candidates], ["new.toml"])
        self.assertEqual(len(scan.skipped), 4)
        self.assertIn("Esse nome está indisponível", "\n".join(scan.skipped))

    def test_invalid_existing_agent_aborts_before_copy(self):
        folder = self.personal / "agents"
        folder.mkdir(parents=True)
        (folder / "bad.toml").write_bytes(b"bad = [")
        with self.assertRaises(AgentsCloudError):
            install_agents([self.agent], self.personal, lambda _: True, lambda _: None)
        self.assertFalse((folder / self.agent.file).exists())

    def test_symlink_source_rejected_when_platform_allows(self):
        target = self.root / "target.toml"
        target.write_bytes(self.agent.content)
        link = self.root / "link.toml"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Criação de symlink não permitida nesta plataforma: {exc}")
        with self.assertRaises(AgentsCloudError):
            read_agent(link)


@unittest.skipUnless(shutil.which("git"), "Git não disponível")
class GitFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentscloud-git-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bare = self.root / "team.git"
        self.seed = self.root / "publisher"
        self.clone = self.root / "reader"
        self.personal = self.root / "codex-home"
        self.env_patch = patch.dict(os.environ, {
            "CODEX_HOME": str(self.personal),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.git(self.root, "init", "--bare", "--initial-branch=equipe", str(self.bare))
        self.git(self.root, "clone", "-o", "time", str(self.bare), str(self.seed))
        self.identity(self.seed)
        write_bundle(self.seed, {"base.toml": agent_bytes()})
        (self.seed / "unrelated.txt").write_text("Arquivo da equipe.\n", encoding="utf-8", newline="\n")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-m", "Base de teste")
        self.git(self.seed, "push", "-u", "time", "HEAD")
        self.git(self.root, "clone", "-o", "time", str(self.bare), str(self.clone))
        self.identity(self.clone)
        self.initial = self.head(self.clone)

    def git(self, cwd, *args, input=None):
        result = subprocess.run(["git", "-C", str(cwd), *args], input=input, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
        return result.stdout

    def identity(self, path):
        self.git(path, "config", "user.name", "AgentsCloud Test")
        self.git(path, "config", "user.email", "test@invalid.example")
        self.git(path, "config", "core.autocrlf", "false")
        self.git(path, "config", "commit.gpgsign", "false")

    def head(self, path):
        return self.git(path, "rev-parse", "HEAD").decode().strip()

    def command(self, command, ui, expected=0):
        status = main([command, "--repo", str(self.clone)], ui=ui)
        self.assertEqual(status, expected, ui.output)
        return ui.output

    def publish(self, filename="new.toml", name="new", description="Novo", maintainer=None):
        existing = {p.name: p.read_bytes() for p in (self.seed / "Agents").glob("*.toml")}
        existing[filename] = agent_bytes(name, description)
        categories = {file: "Desenvolvimento" for file in existing}
        categories[filename] = "Qualidade"
        maintainers = dict(load_bundle(self.seed).maintainers)
        if maintainer is not None:
            maintainers[filename] = maintainer
        write_bundle(self.seed, existing, categories, maintainers)
        self.git(self.seed, "add", "Agents", "catalog.toml", "README.md")
        self.git(self.seed, "commit", "-m", f"Publica {name}")
        self.git(self.seed, "push", "time", "HEAD")

    def personal_agent(self, filename="mine.toml", name="mine"):
        path = self.personal / "agents" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(agent_bytes(name, extra='\n# Comentário mantido.\nmodel = "opcional"\n').replace(b"\n", b"\r\n"))
        return path

    def assert_clean(self):
        self.assertEqual(self.git(self.clone, "status", "--porcelain"), b"")

    def test_update_remote_new_refused_leaves_head_and_personal_untouched(self):
        self.publish()
        ui = FakeUI([False])
        self.command("update", ui)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertFalse((self.clone / "Agents/new.toml").exists())
        self.assertFalse(self.personal.exists())
        self.assertIn("new.toml", ui.output)
        self.assertEqual(len(ui.prompts), 1)
        self.assert_clean()

    def test_update_accepted_then_installs_and_repeated_run_is_idempotent(self):
        self.publish()
        self.command("update", FakeUI([True, True]))
        self.assertEqual(self.head(self.clone), self.head(self.seed))
        installed = self.personal / "agents/new.toml"
        self.assertEqual(installed.read_bytes(), (self.seed / "Agents/new.toml").read_bytes())
        before = installed.stat().st_mtime_ns
        self.command("update", FakeUI([True]))
        self.assertEqual(installed.stat().st_mtime_ns, before)
        self.assert_clean()

    def test_update_up_to_date_can_decline_install_without_creating_folder(self):
        ui = FakeUI([False])
        self.command("update", ui)
        self.assertIn("já está atualizado", ui.output)
        self.assertFalse(self.personal.exists())

    def test_update_removed_agent_does_not_delete_personal_copy(self):
        installed = self.personal_agent("base.toml", "base")
        original = installed.read_bytes()
        (self.seed / "Agents/base.toml").unlink()
        write_bundle(self.seed, {}, {})
        self.git(self.seed, "add", "Agents", "catalog.toml", "README.md")
        self.git(self.seed, "commit", "-m", "Remove do catálogo")
        self.git(self.seed, "push", "time", "HEAD")
        self.command("update", FakeUI([True, True]))
        self.assertEqual(installed.read_bytes(), original)

    def test_update_rejects_remote_invalid_toml_before_merge(self):
        (self.seed / "Agents/base.toml").write_bytes(b"not = [")
        self.git(self.seed, "commit", "-am", "TOML quebrado")
        self.git(self.seed, "push", "time", "HEAD")
        ui = FakeUI()
        self.command("update", ui, 1)
        self.assertIn("TOML inválido", ui.output)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertFalse(self.personal.exists())

    def test_update_rejects_remote_symlink_without_checkout(self):
        oid = self.git(self.seed, "hash-object", "-w", "--stdin", input=b"../outside.toml").decode().strip()
        self.git(self.seed, "update-index", "--cacheinfo", f"120000,{oid},Agents/base.toml")
        self.git(self.seed, "commit", "-m", "Link remoto")
        self.git(self.seed, "push", "time", "HEAD")
        ui = FakeUI()
        self.command("update", ui, 1)
        self.assertIn("links não são aceitos", ui.output)
        self.assertEqual(self.head(self.clone), self.initial)

    def test_dirty_and_staged_checkouts_are_preserved(self):
        path = self.clone / "unrelated.txt"
        path.write_bytes(b"Meu trabalho")
        for staged in (False, True):
            if staged:
                self.git(self.clone, "add", "unrelated.txt")
            ui = FakeUI()
            self.command("upload", ui, 1)
            self.assertIn("não está limpo", ui.output)
            self.assertEqual(path.read_bytes(), b"Meu trabalho")
            self.assertEqual(self.head(self.clone), self.initial)

    def test_missing_upstream_and_detached_head_are_explained(self):
        self.git(self.clone, "branch", "--unset-upstream")
        ui = FakeUI()
        self.command("update", ui, 1)
        self.assertIn("sem upstream", ui.output)
        self.git(self.clone, "checkout", "--detach")
        self.command("update", FakeUI(), 1)

    def test_repository_without_initial_commit_explained(self):
        empty = self.root / "empty"
        empty.mkdir()
        self.git(empty, "init")
        ui = FakeUI()
        self.assertEqual(main(["update", "--repo", str(empty)], ui=ui), 1)
        self.assertIn("commit inicial", ui.output)

    def test_divergence_is_not_merged(self):
        (self.clone / "unrelated.txt").write_bytes(b"Local")
        self.git(self.clone, "commit", "-am", "Local")
        local_head = self.head(self.clone)
        self.publish()
        ui = FakeUI()
        self.command("update", ui, 1)
        self.assertIn("divergência", ui.output)
        self.assertEqual(self.head(self.clone), local_head)

    def test_upload_never_publishes_previous_local_commits(self):
        (self.clone / "unrelated.txt").write_bytes(b"Local")
        self.git(self.clone, "commit", "-am", "Local")
        ui = FakeUI()
        self.command("upload", ui, 1)
        self.assertIn("sem commits locais anteriores", ui.output)
        self.assertEqual(self.head(self.bare), self.initial)

    def test_upload_scan_selective_commit_and_push_preserve_toml_bytes(self):
        source = self.personal_agent()
        original = source.read_bytes()
        ui = FakeUI([True, True], ["Qualidade", ""], selected="mine.toml")
        self.command("upload", ui)
        self.assertEqual((self.clone / "Agents/mine.toml").read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.head(self.clone), self.head(self.bare))
        changed = set(self.git(self.clone, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").decode().splitlines())
        self.assertEqual(changed, {"Agents/mine.toml", "catalog.toml", "README.md"})
        self.assertIn("mine.toml", ui.choices[0][1])
        self.assertEqual(load_bundle(self.clone).categories["mine.toml"], "Qualidade")
        self.assertNotIn("mine.toml", load_bundle(self.clone).maintainers)
        self.assertIn("Responsável: Não informado", ui.output)
        self.assertEqual(main(["index", "--check", "--repo", str(self.clone)], ui=FakeUI()), 0)
        self.assert_clean()

    def test_upload_manual_path_success(self):
        source = self.personal_agent("manual.toml", "manual")
        ui = FakeUI([False, True], [str(source), "Documentação", ""])
        self.command("upload", ui)
        self.assertTrue((self.clone / "Agents/manual.toml").exists())
        self.assertEqual(self.head(self.clone), self.head(self.bare))

    def test_upload_refused_final_and_empty_manual_path_cancel_without_changes(self):
        source = self.personal_agent()
        ui = FakeUI([False, False], [str(source), "Teste", "Equipe Exemplo"])
        self.command("upload", ui)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertFalse((self.clone / "Agents/mine.toml").exists())
        self.command("upload", FakeUI([False], [""]), 130)
        self.assert_clean()

    def test_upload_selection_cancelled_without_copy(self):
        self.personal_agent()
        self.command("upload", FakeUI([True], selected=KeyboardInterrupt()), 130)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertFalse((self.clone / "Agents/mine.toml").exists())

    def test_upload_scan_without_new_agents_reports_unavailable_name(self):
        self.personal_agent("another.toml", "BASE")
        ui = FakeUI([True])
        self.command("upload", ui)
        self.assertIn("Esse nome está indisponível", ui.output)
        self.assertIn("Nenhum agente novo", ui.output)
        self.assert_clean()

    def test_upload_manual_rejects_name_and_filename_case_collisions(self):
        for filename, name in (("other.toml", "BASE"), ("BASE.toml", "different")):
            source = self.personal_agent(filename, name)
            ui = FakeUI([False], [str(source)])
            self.command("upload", ui, 1)
            self.assertIn("Esse nome está indisponível", ui.output)
            self.assertEqual(self.head(self.clone), self.initial)
        self.assert_clean()

    def test_upload_remote_name_taken_during_confirmation_cancels_before_copy(self):
        source = self.personal_agent()
        def race(message):
            if "criar o commit" in message:
                self.publish("other-name.toml", "MINE")
        ui = FakeUI([False, True], [str(source), "Teste", ""], on_confirm=race)
        self.command("upload", ui, 1)
        self.assertIn("Esse nome está indisponível", ui.output)
        self.assertFalse((self.clone / "Agents/mine.toml").exists())
        self.assertEqual(self.head(self.clone), self.initial)
        self.assert_clean()

    def test_upload_invalid_manual_file_does_not_change_checkout(self):
        source = self.personal_agent()
        source.write_bytes(b"bad = [")
        ui = FakeUI([False], [str(source)])
        self.command("upload", ui, 1)
        self.assertIn("TOML inválido", ui.output)
        self.assert_clean()

    def test_commit_failure_preserves_contribution_without_push(self):
        source = self.personal_agent()
        hook = self.clone / ".git/hooks/pre-commit"
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        ui = FakeUI([False, True], [str(source), "Teste", ""])
        self.command("upload", ui, 1)
        self.assertIn("commit não concluído", ui.output)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertEqual(self.head(self.bare), self.initial)
        self.assertEqual((self.clone / "Agents/mine.toml").read_bytes(), source.read_bytes())
        self.assertEqual(load_bundle(self.clone).categories["mine.toml"], "Teste")

    def test_push_rejected_preserves_commit_and_reports_pending_publication(self):
        source = self.personal_agent()
        hook = self.bare / "hooks/pre-receive"
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        ui = FakeUI([False, True], [str(source), "Teste", "Equipe Exemplo"])
        self.command("upload", ui, 1)
        self.assertIn("Publicação pendente", ui.output)
        self.assertEqual(load_bundle(self.clone).maintainers["mine.toml"], "Equipe Exemplo")
        self.assertIn(self.head(self.clone), ui.output)
        self.assertNotEqual(self.head(self.clone), self.initial)
        self.assertEqual(self.head(self.bare), self.initial)
        self.assert_clean()

    def test_crlf_checkout_index_is_valid_and_update_can_install(self):
        self.clone = self.root / "crlf-reader"
        self.git(self.root, "clone", "-c", "core.autocrlf=true", "-o", "time", str(self.bare), str(self.clone))
        self.assertIn(b"\r\n", (self.clone / "README.md").read_bytes())
        self.assert_clean()
        self.assertEqual(main(["validate", "--repo", str(self.clone)], ui=FakeUI()), 0)
        self.command("update", FakeUI([True]))
        self.assertEqual((self.personal / "agents/base.toml").read_bytes(),
                         (self.clone / "Agents/base.toml").read_bytes())


    def test_remote_maintainer_loaded_and_preserved_when_contributing_another_agent(self):
        owner = 'Equipe "Revisão" | API'
        self.publish("owned.toml", "owned", maintainer=owner)
        self.command("update", FakeUI([True, False]))
        self.assertEqual(load_bundle(self.clone).maintainers, {"owned.toml": owner})
        source = self.personal_agent()
        ui = FakeUI([False, True], [str(source), "Qualidade", "Equipe Testes"])
        self.command("upload", ui)
        expected = {"owned.toml": owner, "mine.toml": "Equipe Testes"}
        self.assertEqual(load_bundle(self.clone).maintainers, expected)
        remote_catalog = parse_catalog(self.git(self.bare, "show", "HEAD:catalog.toml"))
        self.assertEqual(remote_catalog.maintainers, expected)
        self.assertIn("Responsável: Equipe Testes", ui.output)
        self.assertNotIn(b"maintainer", (self.clone/"Agents/mine.toml").read_bytes())
        self.assertEqual(main(["index", "--check", "--repo", str(self.clone)], ui=FakeUI()), 0)
        self.assert_clean()

    def test_cancel_at_maintainer_prompt_preserves_catalog_and_head(self):
        source = self.personal_agent()
        old_catalog = (self.clone/"catalog.toml").read_bytes()
        ui = FakeUI([False], [str(source), "Teste", KeyboardInterrupt()])
        self.command("upload", ui, 130)
        self.assertEqual((self.clone/"catalog.toml").read_bytes(), old_catalog)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertFalse((self.clone/"Agents/mine.toml").exists())
        self.assert_clean()

    def test_invalid_remote_maintainer_blocks_update_before_merge(self):
        catalog = self.seed/"catalog.toml"
        catalog.write_bytes(catalog.read_bytes() + b'maintainer = []\n')
        self.git(self.seed, "commit", "-am", "Responsável inválido")
        self.git(self.seed, "push", "time", "HEAD")
        ui = FakeUI()
        self.command("update", ui, 1)
        self.assertIn("Responsável (maintainer)", ui.output)
        self.assertEqual(self.head(self.clone), self.initial)
        self.assertFalse(self.personal.exists())
        self.assert_clean()


    def test_update_accepts_literal_legacy_readme_without_maintainers(self):
        legacy = legacy_readme()
        (self.seed/"README.md").write_bytes(legacy)
        self.git(self.seed, "commit", "-am", "README com índice legado literal")
        self.git(self.seed, "push", "time", "HEAD")
        self.command("update", FakeUI([True, False]))
        self.assertEqual((self.clone/"README.md").read_bytes(), legacy)
        self.assertEqual(load_bundle(self.clone).maintainers, {})
        self.assertEqual(self.head(self.clone), self.head(self.seed))
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
