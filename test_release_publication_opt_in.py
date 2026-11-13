"""A main/tag push verifies artifacts but never publishes a release implicitly."""
from pathlib import Path
import unittest


WORKFLOW = Path(__file__).with_name('.github') / 'workflows' / 'build-windows.yml'
GUARD = "github.event_name == 'workflow_dispatch' && inputs.publish == true && github.ref == 'refs/heads/main'"


def step(text, name):
    marker = '      - name: ' + name + '\n'
    return text.split(marker, 1)[1].split('      - name:', 1)[0]


class ReleasePublicationOptInTests(unittest.TestCase):
    def test_publish_input_is_boolean_and_defaults_to_build_only(self):
        text = WORKFLOW.read_text()
        dispatch = text.split('  workflow_dispatch:\n', 1)[1].split('  push:\n', 1)[0]
        self.assertIn('      publish:\n', dispatch)
        self.assertIn('        type: boolean\n', dispatch)
        self.assertIn('        default: false\n', dispatch)
        self.assertIn('        required: false\n', dispatch)

    def test_every_release_mutation_requires_explicit_main_dispatch(self):
        text = WORKFLOW.read_text()
        for name in ('Require passing CI for the exact release commit',
                     'Publish verified versioned release',
                     'Prepare one-time retirement of releases before v1.0.146-rc3'):
            with self.subTest(name=name):
                self.assertIn('        if: ' + GUARD + '\n', step(text, name))
        publication = step(text, 'Publish verified versioned release')
        for command in ('--create-missing-tag', 'gh release create',
                        'gh release upload', 'gh release edit'):
            self.assertIn(command, publication)
        retirement = step(text, 'Retire the verified snapshot of old releases and tags')
        self.assertIn("if: env.RC3_CLEANUP_READY == 'true'", retirement)
        self.assertEqual(text.count("'RC3_CLEANUP_READY=true'"), 1)

    def test_wiki_publication_has_only_a_manual_trigger(self):
        text = WORKFLOW.with_name('publish-wiki.yml').read_text()
        triggers = text.split('on:\n', 1)[1].split('permissions:', 1)[0]
        self.assertEqual(triggers.strip(), 'workflow_dispatch:')
        self.assertNotIn('  push:', text)

    def test_pushes_keep_verification_and_artifact_uploads(self):
        text = WORKFLOW.read_text()
        for name in ('Run complete regressions and self-test',
                     'Validate packaged GUI and native drag and drop',
                     'Validate silent installer round-trip', 'Upload workflow artifacts'):
            with self.subTest(name=name):
                self.assertNotIn('        if:', step(text, name))
        self.assertIn('    branches:\n      - main\n', text)
        self.assertIn("    tags:\n      - 'v*'\n", text)


if __name__ == '__main__':
    unittest.main()
