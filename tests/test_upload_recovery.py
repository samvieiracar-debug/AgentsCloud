"""Retomada pelo grafo Git, sem journal/autoria inferida; remotos e homes temporários."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_agentscloud as fixtures
from agentscloud.cli import main
from agentscloud.errors import AgentsCloudError
from agentscloud.git import Repository


class RecoveryTests(unittest.TestCase):
    setUp = fixtures.GitFlowTests.setUp
    git = fixtures.GitFlowTests.git
    identity = fixtures.GitFlowTests.identity
    head = fixtures.GitFlowTests.head
    personal_agent = fixtures.GitFlowTests.personal_agent
    publish = fixtures.GitFlowTests.publish

    def invoke(self, ui, code=0, command="upload"):
        actual = main([command, "--repo", str(self.clone)], ui=ui)
        self.assertEqual(actual, code, ui.output)
        return ui.output

    def local_commit(self, name="pending.txt"):
        (self.clone / name).write_text(name, encoding="utf-8")
        self.git(self.clone, "add", name)
        self.git(self.clone, "commit", "-m", "Manual " + name)
        return self.head(self.clone)

    def test_rejected_push_can_resume_exact_commit_without_personal_source_or_scan(self):
        source = self.personal_agent()
        hook = self.bare / "hooks/pre-receive"
        hook.write_bytes(b"#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.invoke(fixtures.FakeUI([False, True, False], [str(source), "Teste", ""]), 1)
        commit = self.head(self.clone)
        count = self.git(self.clone, "rev-list", "--count", "HEAD")
        hook.unlink()
        source.unlink()
        ui = fixtures.FakeUI([True])
        self.invoke(ui)
        self.assertEqual(self.head(self.bare), commit)
        self.assertEqual(self.head(self.clone), commit)
        self.assertEqual(self.git(self.clone, "rev-list", "--count", "HEAD"), count)
        self.assertEqual(len(ui.prompts), 1)
        self.assertIn("TODOS", ui.output)

    def test_multiple_manual_commits_require_complete_preview_and_specific_consent(self):
        first = self.local_commit("first.txt")
        second = self.local_commit("second.txt")
        ui = fixtures.FakeUI([False])
        self.invoke(ui)
        for value in (first, second, "first.txt", "second.txt", "2 commit(s)"):
            self.assertIn(value, ui.output)
        self.assertEqual(self.head(self.bare), self.initial)
        ui = fixtures.FakeUI([True])
        self.invoke(ui)
        self.assertEqual(self.head(self.bare), second)
        self.assertEqual(self.head(self.clone), second)
        self.assertEqual(len(ui.prompts), 1)

    def test_eof_and_interrupt_never_consent_to_pending_commits(self):
        head = self.local_commit()
        for exception in (EOFError(), KeyboardInterrupt()):
            def abort(_):
                raise exception
            self.invoke(fixtures.FakeUI(on_confirm=abort), 130)
            self.assertEqual(self.head(self.bare), self.initial)
            self.assertEqual(self.head(self.clone), head)

    def test_authentication_failure_allows_one_consent_after_review_same_sha(self):
        head = self.local_commit()
        original = Repository.push
        shas = []
        def attempt(repo, target, commit):
            shas.append(commit)
            if len(shas) == 1:
                raise AgentsCloudError("Authentication failed (simulada)")
            original(repo, target, commit)
        ui = fixtures.FakeUI([True, True])
        with patch.object(Repository, "push", attempt):
            self.invoke(ui)
        self.assertEqual(shas, [head, head])
        self.assertEqual(self.head(self.bare), head)
        self.assertEqual(len(ui.prompts), 2)

    def test_retry_is_bounded_and_preserves_commit(self):
        head = self.local_commit()
        with patch.object(Repository, "push", side_effect=AgentsCloudError("Authentication failed")) as push:
            ui = fixtures.FakeUI([True, True])
            self.invoke(ui, 1)
        self.assertEqual(push.call_count, 2)
        self.assertEqual(self.head(self.clone), head)
        self.assertEqual(self.head(self.bare), self.initial)
        self.assertIn("duas tentativas", ui.output)

    def test_accepted_push_and_lost_response_with_later_remote_commit_is_confirmed(self):
        head = self.local_commit()
        original = Repository.push
        calls = []
        def lost(repo, target, commit):
            calls.append(commit)
            original(repo, target, commit)
            self.git(self.seed, "pull", "--ff-only")
            self.publish("later.toml", "later")
            raise AgentsCloudError("Resposta perdida após aceitação simulada")
        ui = fixtures.FakeUI([True])
        with patch.object(Repository, "push", lost):
            self.invoke(ui)
        self.assertEqual(calls, [head])
        self.assertNotEqual(self.head(self.bare), head)
        self.assertEqual(self.head(self.clone), head)
        self.assertIn("Publicação confirmada", ui.output)

    def test_failed_post_push_query_remains_uncertain_without_retry(self):
        head = self.local_commit()
        original = Repository.fetch_target
        count = []
        def lookup(repo, target):
            count.append(1)
            if len(count) >= 3:
                raise AgentsCloudError("conexão indisponível simulada")
            return original(repo, target)
        with patch.object(Repository, "fetch_target", lookup), \
             patch.object(Repository, "push", side_effect=AgentsCloudError("resposta perdida")) as push:
            ui = fixtures.FakeUI([True])
            self.invoke(ui, 1)
        self.assertEqual(push.call_count, 1)
        self.assertIn("Resultado incerto", ui.output)
        self.assertEqual(self.head(self.clone), head)

    def test_changed_head_during_consent_prevents_unreviewed_publication(self):
        self.local_commit()
        def race(_):
            self.local_commit("unreviewed.txt")
        ui = fixtures.FakeUI([True], on_confirm=race)
        self.invoke(ui, 1)
        self.assertIn("HEAD/branch mudou", ui.output)
        self.assertEqual(self.head(self.bare), self.initial)

    def test_pushurl_is_queried_and_used_instead_of_fetch_url(self):
        alternate = self.root / "alternate.git"
        self.git(self.root, "clone", "--bare", str(self.bare), str(alternate))
        self.git(self.clone, "remote", "set-url", "--push", "time", str(alternate))
        head = self.local_commit()
        self.invoke(fixtures.FakeUI([True]))
        self.assertEqual(self.head(alternate), head)
        self.assertEqual(self.head(self.bare), self.initial)

    def test_changed_or_multiple_push_destinations_never_publish(self):
        alternate = self.root / "alternate.git"
        self.git(self.root, "clone", "--bare", str(self.bare), str(alternate))
        self.local_commit()
        def race(_):
            self.git(self.clone, "remote", "set-url", "--push", "time", str(alternate))
        ui = fixtures.FakeUI([True], on_confirm=race)
        self.invoke(ui, 1)
        self.assertIn("Destino de push mudou", ui.output)
        self.git(self.clone, "remote", "set-url", "--add", "--push", "time", str(self.bare))
        self.invoke(fixtures.FakeUI(), 1)
        self.assertEqual(self.head(self.bare), self.initial)
        self.assertEqual(self.head(alternate), self.initial)

    def test_explicit_sha_push_does_not_publish_tags_or_other_refs(self):
        head = self.local_commit()
        self.git(self.clone, "tag", "-a", "private-tag", "-m", "private")
        self.git(self.clone, "branch", "private-branch")
        self.git(self.clone, "config", "push.followTags", "true")
        self.git(self.clone, "config", "remote.time.push", "refs/heads/*:refs/heads/*")
        self.git(self.clone, "config", "remote.time.mirror", "true")
        self.invoke(fixtures.FakeUI([True]))
        refs = self.git(self.bare, "show-ref").decode()
        self.assertNotIn("private", refs)
        self.assertEqual(self.head(self.bare), head)

    def test_invalid_catalog_index_cannot_bypass_validation_as_pending_commit(self):
        (self.clone / "README.md").write_text("invalid index", encoding="utf-8")
        self.git(self.clone, "commit", "-am", "invalid manual index")
        ui = fixtures.FakeUI()
        with patch.object(Repository, "push") as push:
            self.invoke(ui, 1)
        push.assert_not_called()
        self.assertFalse(ui.prompts)
        self.assertEqual(self.head(self.bare), self.initial)

    def test_update_ahead_uses_local_catalog_only_after_personal_consent(self):
        head = self.local_commit()
        ui = fixtures.FakeUI([False])
        self.invoke(ui, command="update")
        self.assertIn("ainda não publicados", ui.output)
        self.assertFalse(self.personal.exists())
        self.invoke(fixtures.FakeUI([True]), command="update")
        self.assertTrue((self.personal / "agents/base.toml").exists())
        self.assertEqual(self.head(self.clone), head)
        self.assertEqual(self.head(self.bare), self.initial)

    def test_divergence_refuses_publication_without_rewriting_history(self):
        head = self.local_commit()
        self.publish()
        ui = fixtures.FakeUI()
        self.invoke(ui, 1)
        self.assertIn("divergente", ui.output)
        self.assertEqual(self.head(self.clone), head)


if __name__ == "__main__":
    unittest.main()
