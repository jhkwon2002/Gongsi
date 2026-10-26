import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('gongsi_autodeploy',ROOT/'deploy/autodeploy.py')
auto=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto)
OLD='a'*40
NEW='b'*40
OTHER='c'*40


def run(status='completed',conclusion='success',**fields):
    value={'head_sha':NEW,'event':'push','head_branch':'main','path':auto.WORKFLOW,
           'status':status,'conclusion':conclusion,'run_number':1,'run_attempt':1}
    value.update(fields)
    return value


class AutomaticDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.current=self.root/'current'
        self.current.mkdir()
        (self.current/'RELEASE').write_text(OLD)
        self.marker=self.root/'operator'
        self.marker.write_text(OLD)
        patches=[patch.object(auto,'CURRENT',self.current),patch.object(auto,'OPERATOR_MARKER',self.marker)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def call(self,runs=None,memory=200000,new_head=NEW):
        replies=[{'object':{'sha':NEW}},{'workflow_runs':runs if runs is not None else [run()]},{'object':{'sha':new_head}}]
        def activate(command,**kwargs):
            self.assertEqual(command,['/usr/local/sbin/deploy-gongsi',NEW])
            (self.current/'RELEASE').write_text(NEW)
        with patch.object(auto,'get_json',side_effect=replies),patch.object(auto,'available_memory_kb',return_value=memory),patch.object(auto.subprocess,'run',side_effect=activate) as deploy,patch.object(auto,'refresh_operator_tools') as refresh:
            result=auto.update_once()
        return result,deploy,refresh

    def test_successful_exact_head_is_deployed_and_operator_refreshed(self):
        result,deploy,refresh=self.call()
        self.assertEqual(result['result'],'deployed')
        deploy.assert_called_once()
        refresh.assert_called_once_with(self.current.resolve())

    def test_failed_ci_never_runs_deployment(self):
        result,deploy,_=self.call([run(conclusion='failure')])
        self.assertEqual(result['result'],'deferred_ci_failed')
        deploy.assert_not_called()
        self.assertEqual((self.current/'RELEASE').read_text(),OLD)

    def test_pending_ci_never_runs_deployment(self):
        result,deploy,_=self.call([run(status='in_progress',conclusion=None)])
        self.assertEqual(result['result'],'deferred_ci_waiting')
        deploy.assert_not_called()

    def test_other_commit_success_cannot_authorize_head(self):
        result,deploy,_=self.call([run(head_sha=OTHER)])
        self.assertEqual(result['result'],'deferred_ci_waiting')
        deploy.assert_not_called()

    def test_other_workflow_success_cannot_authorize_head(self):
        result,deploy,_=self.call([run(path='.github/workflows/unrelated.yml')])
        self.assertEqual(result['result'],'deferred_ci_waiting')
        deploy.assert_not_called()

    def test_newer_failed_attempt_overrides_old_success(self):
        self.assertEqual(auto.ci_decision([run(),run(conclusion='failure',run_attempt=2)],NEW),'failed')

    def test_pull_request_run_cannot_authorize_production(self):
        self.assertEqual(auto.ci_decision([run(event='pull_request')],NEW),'waiting')

    def test_low_memory_defers_without_installing_or_deploying(self):
        result,deploy,_=self.call(memory=20000)
        self.assertEqual(result['result'],'deferred_low_memory')
        deploy.assert_not_called()

    def test_superseded_head_defers(self):
        result,deploy,_=self.call(new_head=OTHER)
        self.assertEqual(result['result'],'deferred_main_changed')
        deploy.assert_not_called()

    def test_unchanged_head_needs_only_one_api_request(self):
        with patch.object(auto,'get_json',return_value={'object':{'sha':OLD}}) as api,patch.object(auto.subprocess,'run') as deploy:
            result=auto.update_once()
        self.assertEqual(result['result'],'unchanged')
        api.assert_called_once()
        deploy.assert_not_called()

    def test_deployment_failure_does_not_refresh_operator_or_claim_success(self):
        with patch.object(auto,'get_json',side_effect=[{'object':{'sha':NEW}},{'workflow_runs':[run()]},{'object':{'sha':NEW}}]),patch.object(auto,'available_memory_kb',return_value=200000),patch.object(auto.subprocess,'run',side_effect=RuntimeError),patch.object(auto,'refresh_operator_tools') as refresh:
            with self.assertRaises(RuntimeError):
                auto.update_once()
            refresh.assert_not_called()

    def test_invalid_sha_is_rejected(self):
        with patch.object(auto,'get_json',return_value={'object':{'sha':'main; false'}}),patch.object(auto.subprocess,'run') as deploy:
            with self.assertRaisesRegex(ValueError,'SHA'):
                auto.update_once()
            deploy.assert_not_called()
