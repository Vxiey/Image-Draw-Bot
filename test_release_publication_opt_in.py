"""A main/tag push verifies artifacts but never publishes a release implicitly."""
from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).with_name('.github') / 'workflows' / 'build-windows.yml'
GUARD = "github.event_name == 'workflow_dispatch' && inputs.publish == true && github.ref == 'refs/heads/main'"


def step(text, name):
    marker = '      - name: ' + name + '\n'
    return text.split(marker, 1)[1].split('      - name:', 1)[0]


class ReleasePublicationOptInTests(unittest.TestCase):
    def test_current_ci_and_publishing_actions_are_pinned_and_checkout_drops_credentials(self):
        for filename in ('ci.yml', 'build-windows.yml', 'publish-wiki.yml'):
            text = WORKFLOW.with_name(filename).read_text()
            steps = re.split(r'^      - ', text, flags=re.MULTILINE)[1:]
            uses = [s for s in steps if re.search(r'^\s*uses:', s, re.MULTILINE)]
            self.assertTrue(uses, filename)
            for action in uses:
                with self.subTest(workflow=filename, step=action.splitlines()[0]):
                    self.assertRegex(action, r'(?m)^\s*uses: [\w.-]+/[\w.-]+@[0-9a-f]{40}(?:\s*#.*)?$')
                    if 'uses: actions/checkout@' in action:
                        self.assertRegex(action, r'(?m)^          persist-credentials: false$')

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

    def test_install_and_both_uploads_select_only_the_verified_version(self):
        text = WORKFLOW.read_text()
        version = step(text, 'Read the verified source version')
        self.assertIn('from Version import APP_VERSION', version)
        self.assertIn('"version=$version" >> $env:GITHUB_OUTPUT', version)
        install = step(text, 'Validate silent installer round-trip')
        token = '${{ steps.release_version.outputs.version }}'
        self.assertIn('RELEASE_VERSION: ' + token, install)
        self.assertIn('Get-Item -LiteralPath "release/ImageDrawBot-${env:RELEASE_VERSION}-Windows-x64-Setup.exe"', install)
        self.assertNotIn('Select-Object -First', install)
        for name in ('Validate packaged release', 'Revalidate downloaded release files'):
            self.assertIn('ReleaseCandidateHardening.py --release-dir release --strict-inventory', step(text, name))

        suffixes = ('Windows-x64.zip', 'Windows-x64-Setup.exe', 'SHA256.txt', 'manifest.json')
        upload = step(text, 'Upload workflow artifacts')
        paths = re.findall(r'^            (release/.+)$', upload, re.MULTILINE)
        self.assertCountEqual(paths, [f'release/ImageDrawBot-{token}-{suffix}' for suffix in suffixes])
        publish = step(text, 'Publish verified versioned release')
        self.assertIn('from Version import APP_VERSION', publish)
        paths = re.findall(r'^            "(release/.+)"$', publish, re.MULTILINE)
        self.assertCountEqual(paths, [f'release/ImageDrawBot-$version-{suffix}' for suffix in suffixes])
        self.assertIn('gh release upload $tag --clobber @assets', publish)


if __name__ == '__main__':
    unittest.main()
