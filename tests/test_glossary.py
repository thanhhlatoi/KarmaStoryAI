import json
import unittest

from karma import glossary as gl
from karma import llm
from karma.cli_prep import build
from karma.cli_usage import summarize
from .test_pipeline import Workspace

GLOSSARY = """<!-- source-sha: abc -->
## Names
- cụ Mận => Frau Mận; avoid: die Alte
- Bờm / Lâm => Bờm / Lâm
## Style
- ruhig erzählen
## Pronunciation
- Bờm => Böm; avoid: ignored
"""


class GlossaryTests(unittest.TestCase):
    def test_pronunciation_is_separate_from_entries(self):
        self.assertEqual(gl.parse_pronunciation(GLOSSARY), {'Bờm': 'Böm; avoid: ignored'.split(';')[0]})
        self.assertNotIn('Böm', [e[1] for e in gl.parse_entries(GLOSSARY)])

    def test_spoken_text_keeps_native_letters(self):
        text, stripped = gl.spoken_text('Bờm grüßte Frau Mận und Tín.', 'de', {'Bờm': 'Böm'})
        self.assertEqual(text, 'Böm grüßte Frau Man und Tin.')
        self.assertEqual(stripped, ['Mận', 'Tín'])
        text, stripped = gl.spoken_text('El señor Tín habló con Lễ.', 'es', {})
        self.assertEqual(text, 'El señor Tín habló con Le.')   # í, ñ của tiếng Tây Ban Nha giữ nguyên
        self.assertEqual(stripped, ['Lễ'])

    def test_pronunciation_matches_genitive_and_quotes_keep_punctuation(self):
        from karma.cli_prep import plain_text
        text, stripped = gl.spoken_text('In Hảos Hof und Hảo’s gate.', 'de', {'Hảo': 'Hao'})
        self.assertEqual((text, stripped), ('In Haos Hof und Hao’s gate.', []))
        self.assertEqual(plain_text('„Mir ist so kalt.“', 'de'), '„Mir ist so kalt.“')
        self.assertEqual(plain_text('«¿Quién es?»', 'es'), '«¿Quién es?»')
        self.assertEqual(plain_text('Er ging', 'de'), 'Er ging.')

    def test_chapter_stamp_only_tracks_relevant_entries(self):
        chapter = 'Bờm ngồi ăn cơm.'
        base = gl.chapter_stamp(GLOSSARY, chapter)
        self.assertEqual(base, gl.chapter_stamp(GLOSSARY.replace('die Alte', 'die Greisin'), chapter))
        self.assertNotEqual(base, gl.chapter_stamp(GLOSSARY.replace('ruhig', 'langsam'), chapter))
        self.assertEqual(base, gl.chapter_stamp(GLOSSARY + '- Lễ => Lễ\n', chapter))
        self.assertNotEqual(base, gl.chapter_stamp(GLOSSARY.replace('Bờm / Lâm => Bờm', 'Bờm / Lâm => Bom'), chapter))

    def test_source_status(self):
        self.assertEqual(gl.source_status(gl.header('a') + '\n- x => y', 'a'), 'ok')
        self.assertEqual(gl.source_status(gl.header('a'), 'b'), 'stale')
        self.assertEqual(gl.source_status('- x => y', 'a'), 'unknown')


class PrepAndUsageTests(Workspace):
    def test_build_numbers_german_and_spanish_chapters(self):
        for lang, word in (('de', 'Kapitel'), ('es', 'Capítulo')):
            script = f"# TITEL\n\n## {word} 1. Eins\nErster Text.\n\n## {word} 2. Zwei\nZweiter Text.\n"
            build(script, lang, self.root, self.root / 'missing.md')
            scenes = json.loads((self.root / f'{lang}.scenes.json').read_text())
            self.assertEqual([s['chapter'] for s in scenes], [1, 1, 2])

    def test_usage_groups_by_tag_and_role(self):
        log = self.root / 'work' / 'llm.log'
        log.parent.mkdir(exist_ok=True)
        entries = [{'tag': '017/de', 'role': 'writer', 'prompt_length': 300, 'answer_length': 30,
                    'seconds': 60, 'success': True, 'time': '2026-11-11T10:00'},
                   {'tag': '017/de', 'role': 'writer', 'prompt_length': 300, 'seconds': 6,
                    'success': False, 'time': '2026-11-11T10:05'},
                   {'role': 'scorer', 'prompt_length': 90, 'seconds': 1, 'success': True,
                    'time': '2026-11-10T10:00'}]
        log.write_text('\n'.join(map(json.dumps, entries)) + '\nhỏng\n')
        rows = dict(summarize())
        self.assertEqual(rows[('017/de', 'writer')]['calls'], 2)
        self.assertEqual(rows[('017/de', 'writer')]['failed'], 1)
        self.assertEqual(rows[('(không nhãn)', 'scorer')]['prompt'], 90)
        self.assertEqual(len(summarize('017')), 1)
        self.assertEqual(len(summarize(since='2026-11-11')), 1)

    def test_tag_is_logged_and_restored(self):
        self.configure(llm={'writer': {'type': 'cli', 'cmd': ['cat'], 'attempts': 1}})
        with llm.tagged('017/en'):
            self.assertEqual(llm.complete('writer', 'xin chào'), 'xin chào')
        self.assertIsNone(llm._TAG)
        entry = json.loads((self.root / 'work' / 'llm.log').read_text().splitlines()[-1])
        self.assertEqual((entry['tag'], entry['answer_length']), ('017/en', 8))
        self.assertNotIn('xin chào', (self.root / 'work' / 'llm.log').read_text())
