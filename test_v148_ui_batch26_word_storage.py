"""Actual word import must leave a dictionary that the startup reader accepts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import DrawBot
import RuntimePaths
from WordGuesser import MAX_WORD_LIST_BYTES, find_candidates, load_words
from test_guesser_drop import Value


def alphabetic_suffix(index):
    return ''.join(chr(97 + index // (26 ** place) % 26) for place in (3, 2, 1, 0))


def dictionary_payload(prefix, count, *, extend_last=False):
    words = [prefix + alphabetic_suffix(index) for index in range(count)]
    if extend_last:
        words[-1] += 'a'
    return '\n'.join(words).encode('utf-8')


class ImportedWordStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'incoming.txt'
        self.saved = self.root / 'guess-words.txt'
        self.saved.write_bytes(b'cat\ndog\n')
        self.original_bytes = self.saved.read_bytes()
        self.app = SimpleNamespace(activity=None, guess_words=('cat', 'dog'),
            word_source=Value('Existing dictionary'), guess_result=Value('Existing result'),
            update_guesses=Mock())

    def import_payload(self, payload):
        self.source.write_bytes(payload)
        with patch.object(DrawBot, 'DATA_DIR', self.root), \
             patch.object(DrawBot.filedialog, 'askopenfilename', return_value=str(self.source)):
            DrawBot.DrawBotApp.import_words(self.app)

    def assert_previous_dictionary_survives(self):
        self.assertEqual(self.saved.read_bytes(), self.original_bytes)
        self.assertEqual(load_words(self.saved), ('cat', 'dog'))
        self.assertEqual(self.app.guess_words, ('cat', 'dog'))
        self.assertEqual(self.app.word_source.get(), 'Existing dictionary')
        self.app.update_guesses.assert_not_called()
        self.assertEqual(sorted(path.name for path in self.root.iterdir()),
                         ['guess-words.txt', 'incoming.txt'])

    def test_input_limit_without_final_newline_cannot_publish_unreadable_dictionary(self):
        payload = dictionary_payload('a' * 75, 25_000, extend_last=True)
        self.assertEqual(len(payload), MAX_WORD_LIST_BYTES)
        self.source.write_bytes(payload)
        self.assertEqual(len(load_words(self.source)), 25_000)
        self.import_payload(payload)
        self.assert_previous_dictionary_survives()
        self.assertIn('normalized word list', self.app.guess_result.get())

    def test_unicode_casefold_expansion_is_checked_before_publication(self):
        payload = dictionary_payload('\u023a' * 75, 12_000)
        self.assertEqual(len(payload), 1_859_999)
        self.source.write_bytes(payload)
        normalized = load_words(self.source)
        self.assertEqual(len(normalized), 12_000)
        self.assertEqual(len(('\n'.join(normalized) + '\n').encode('utf-8')), 2_760_000)
        self.import_payload(payload)
        self.assert_previous_dictionary_survives()
        self.assertIn('normalized word list', self.app.guess_result.get())

    def test_exact_saved_limit_round_trips_through_startup_reader(self):
        payload = dictionary_payload('a' * 75, 25_000)
        self.assertEqual(len(payload), MAX_WORD_LIST_BYTES - 1)
        self.import_payload(payload)
        self.assertEqual(self.saved.stat().st_size, MAX_WORD_LIST_BYTES)
        self.assertEqual(load_words(self.saved), self.app.guess_words)
        self.assertEqual(len(self.app.guess_words), 25_000)
        self.assertEqual(self.app.word_source.get(), '25000 words · incoming.txt')
        self.app.update_guesses.assert_called_once_with()
        self.assertEqual(find_candidates(self.app.guess_words, self.app.guess_words[-1], '79'),
                         [self.app.guess_words[-1]])

    def test_canonical_unicode_import_and_failed_atomic_replace_preserve_correct_owner(self):
        payload = '\ufeffKATT\n# comment\nRÖD BIL\nkatt\n\u023a\n'.encode('utf-8')
        self.import_payload(payload)
        self.assertEqual(self.app.guess_words, ('katt', 'röd bil', '\u2c65'))
        self.assertEqual(load_words(self.saved), self.app.guess_words)
        self.assertEqual(self.saved.read_bytes(), 'katt\nröd bil\n\u2c65\n'.encode('utf-8'))
        self.original_bytes = self.saved.read_bytes()
        prior_words = self.app.guess_words
        prior_source = self.app.word_source.get()
        self.app.update_guesses.reset_mock()
        with patch.object(RuntimePaths.os, 'replace', side_effect=PermissionError(13, 'denied')):
            self.import_payload(b'new word\n')
        self.assertEqual(self.saved.read_bytes(), self.original_bytes)
        self.assertEqual(load_words(self.saved), prior_words)
        self.assertIs(self.app.guess_words, prior_words)
        self.assertEqual(self.app.word_source.get(), prior_source)
        self.app.update_guesses.assert_not_called()
        self.assertIn('denied', self.app.guess_result.get())
        self.assertEqual(sorted(path.name for path in self.root.iterdir()),
                         ['guess-words.txt', 'incoming.txt'])


if __name__ == '__main__':
    unittest.main()
