import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import translate_review as tr

PROJECT = Path(__file__).resolve().parent.parent
SOURCE = '# TRUYỆN\n\n## Chương 1. Một\nAlpha alpha alpha.\n\n## Chương 2. Hai\nBeta beta.\n\n## Chương 3. Ba\nGamma.\n'
GLOSSARY = '## Names\n- cụ Mận => Frau Mận; avoid: die Alte\n'


def review_json(score=9, **extra):
    data = {'criteria': dict.fromkeys(tr.WEIGHTS, score), 'summary': 's', 'missing_events': [],
            'fixes': [{'quote': 'q', 'issue': 'i', 'suggested': 's'}], 'source_issues': []}
    data.update(extra)
    return json.dumps(data)


class Fake:
    """Giả llm.complete: ghi lại prompt, trả lời theo vai trò."""
    def __init__(self, review_scores=None, translations=None):
        self.calls = []
        self.review_scores = review_scores or {}
        self.translations = translations or {}

    def __call__(self, role, prompt):
        self.calls.append((role, prompt))
        if role == 'writer' and 'translation glossary' in prompt:
            return GLOSSARY
        if role == 'writer':
            marker = next(m for m in ('Alpha', 'Beta', 'Gamma') if m in prompt.split('VIETNAMESE CHAPTER:')[1])
            revising = 'This is a REVISION' in prompt
            text = self.translations.get((marker, revising), f'{marker}-{"fixed" if revising else "v1"}')
            title = '# TITEL\n\n' if marker == 'Alpha' else ''
            return f'{title}## {marker}\n{text}\n{tr.END}'
        marker = next(m for m in ('Alpha', 'Beta', 'Gamma') if m in prompt.split('CHƯƠNG VIỆT:')[1])
        translation = prompt.split('CHƯƠNG DỊCH:')[1]
        score = self.review_scores.get((marker, 'fixed' in translation), 9)
        return 'Đây là review:\n' + review_json(score)


class SplitAndGlossary(unittest.TestCase):
    def test_split_keeps_title_with_first_chapter(self):
        parts = tr.split_chapters(SOURCE)
        self.assertEqual(len(parts), 3)
        self.assertTrue(parts[0].startswith('# TRUYỆN'))
        self.assertTrue(parts[1].startswith('## Chương 2'))

    def test_split_fallback_without_headings(self):
        text = '\n\n'.join(['word ' * 1000] * 5)
        self.assertEqual(len(tr.split_chapters(text)), 2)  # 3 đoạn (>=2500 từ) + 2 đoạn

    def test_glossary_parse_and_check(self):
        entries = tr.parse_glossary(GLOSSARY + '- mõ => Holzklapper; avoid: Tempelblock, "Gebetsblock"\n')
        self.assertEqual(entries[1], ('mõ', 'Holzklapper', ['Tempelblock', 'Gebetsblock']))
        issues = tr.glossary_issues('Da kam Die Alte, die Altenpflege nicht.', entries)
        self.assertEqual(len(issues), 1)
        self.assertIn('die Alte', issues[0])

    def test_short_avoid_variants_are_ignored(self):
        entries = tr.parse_glossary('- cụ Mận => Frau Mận; avoid: Man, Sie, die Alte\n')
        self.assertEqual(entries[0][2], ['die Alte'])
        self.assertEqual(tr.glossary_issues('Sie sagte, man könne gehen.', entries), [])

    def test_clean_strips_invisible_and_marker(self):
        self.assertEqual(tr.clean('Ke­gel hut ' + tr.END), 'Kegel hut')

    def test_parse_review_rejects_bad_scores(self):
        with self.assertRaises(ValueError):
            tr.parse_review('{"criteria": {"fidelity": 11}}')


class Pipeline(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        cfg = json.loads((PROJECT / 'config.json').read_text())
        cfg['target_minutes'] = [0.001, 1000]   # chương giả rất ngắn
        (self.root / 'config.json').write_text(json.dumps(cfg))
        env = patch.dict(os.environ, {'KARMA_ROOT': str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.source = self.root / 'src.md'
        self.source.write_text(SOURCE, encoding='utf-8')
        self.out = self.root / 'out'

    def run_with(self, fake, **kwargs):
        with patch('karma.llm.complete', fake):
            tr.process(self.source, self.out, 'de', **kwargs)

    def test_each_call_sees_only_one_chapter(self):
        fake = Fake()
        self.run_with(fake)
        for role, prompt in fake.calls:
            if 'CHƯƠNG VIỆT:' in prompt:
                body = prompt.split('CHƯƠNG VIỆT:')[1]
                self.assertEqual(sum(w in body for w in ('Alpha', 'Beta', 'Gamma')), 1)
            if 'VIETNAMESE CHAPTER:' in prompt:
                body = prompt.split('VIETNAMESE CHAPTER:')[1]
                self.assertEqual(sum(w in body for w in ('Alpha', 'Beta', 'Gamma')), 1)
        # 1 glossary + 3 dịch + 3 review, không vòng sửa
        self.assertEqual(len(fake.calls), 7)
        review = json.loads((self.out / 'de.review.json').read_text())
        self.assertTrue(review['pass'])
        self.assertTrue((self.out / 'de.md').read_text().startswith('# TITEL'))

    def test_second_chapter_gets_continuity_tail(self):
        fake = Fake()
        self.run_with(fake)
        writer = [p for r, p in fake.calls if r == 'writer' and 'VIETNAMESE CHAPTER:' in p]
        self.assertNotIn('CONTINUITY ONLY', writer[0])
        self.assertIn('CONTINUITY ONLY', writer[1])
        self.assertIn('Alpha-v1', writer[1])

    def test_rerun_uses_cache(self):
        self.run_with(Fake())
        fake = Fake()
        self.run_with(fake)
        self.assertEqual(fake.calls, [])

    def test_only_failing_chapter_is_revised(self):
        fake = Fake(review_scores={('Beta', False): 5})
        self.run_with(fake)
        revisions = [p for r, p in fake.calls if r == 'writer' and 'This is a REVISION' in p]
        self.assertEqual(len(revisions), 1)
        self.assertIn('Beta-v1', revisions[0])          # sửa dựa trên bản dịch cũ
        self.assertIn('"q" — i → s', revisions[0])      # kèm danh sách fixes
        self.assertEqual(len(fake.calls), 1 + 3 + 3 + 1 + 1)
        review = json.loads((self.out / 'de.review.json').read_text())
        self.assertEqual([c['round'] for c in review['chapters']], [1, 2, 1])
        self.assertTrue(review['pass'])

    def test_glossary_violation_forces_revision_without_extra_review_failure(self):
        fake = Fake(translations={('Gamma', False): 'Da kam die Alte.'})
        self.run_with(fake)
        revisions = [p for r, p in fake.calls if r == 'writer' and 'This is a REVISION' in p]
        self.assertEqual(len(revisions), 1)
        self.assertIn('die Alte', revisions[0])
        self.assertIn('Gamma-fixed', (self.out / 'de.md').read_text())

    def test_stops_at_max_rounds_and_reports_fail(self):
        fake = Fake(review_scores={('Beta', False): 5, ('Beta', True): 5})
        self.run_with(fake, max_rounds=2)
        review = json.loads((self.out / 'de.review.json').read_text())
        self.assertFalse(review['pass'])
        self.assertIn('Chương 02', (self.out / 'de.review.md').read_text())

    def test_truncated_chapter_continues_on_same_chapter_only(self):
        answers = iter(['## Alpha\nđầu', 'cuối\n' + tr.END])

        def fake(role, prompt):
            if role == 'writer' and 'translation glossary' in prompt:
                return GLOSSARY
            if role == 'writer' and 'Alpha' in prompt.split('VIETNAMESE CHAPTER:')[1]:
                return next(answers)
            return Fake()(role, prompt)

        self.source.write_text('## Chương 1\nAlpha.\n', encoding='utf-8')
        self.run_with(fake)
        self.assertIn('đầu\ncuối', (self.out / 'de.md').read_text())

    def test_changed_source_chapter_is_retranslated_others_kept(self):
        self.run_with(Fake())
        self.source.write_text(SOURCE.replace('Beta beta', 'Beta beta changed'), encoding='utf-8')
        with self.assertRaises(ValueError):            # glossary cũ tạo cho nguồn khác: chặn
            self.run_with(Fake())
        fake = Fake()
        self.run_with(fake, accept_glossary=True)
        self.assertEqual(len([1 for r, _ in fake.calls if r == 'writer']), 1)

    def test_glossary_has_source_header_and_asks_for_pronunciation(self):
        fake = Fake()
        self.run_with(fake, glossary_only=True)
        text = (self.out / 'glossary.de.md').read_text()
        self.assertEqual(tr.gl.source_status(text, SOURCE), 'ok')
        self.assertIn('## Pronunciation', fake.calls[0][1])

    def test_glossary_edit_retranslates_only_affected_chapter(self):
        self.run_with(Fake())
        path = self.out / 'glossary.de.md'
        path.write_text(path.read_text() + '- Gamma => Gammawort; avoid: Falschwort\n')
        fake = Fake()
        self.run_with(fake)
        writer = [p for r, p in fake.calls if r == 'writer']
        self.assertEqual(len(writer), 1)
        self.assertIn('Gamma', writer[0].split('VIETNAMESE CHAPTER:')[1])
        path.write_text(path.read_text() + '\n## Pronunciation\n- Mận => Man\n')
        fake = Fake()
        self.run_with(fake)                             # phát âm không ảnh hưởng bản dịch
        self.assertEqual(fake.calls, [])

    def test_prep_translation_uses_pronunciation_and_detects_edits(self):
        from karma.cli_prep import prep_translation
        fake = Fake(translations={('Beta', False): 'Frau Mận sprach mit Bờm.'})
        self.run_with(fake)
        path = self.out / 'glossary.de.md'
        path.write_text(path.read_text() + '\n## Pronunciation\n- Bờm => Böm\n')
        prep_translation(self.out, 'de')
        tts = (self.out / 'de.tts.txt').read_text()
        self.assertIn('Frau Man sprach mit Böm.', tts)   # Mận tự bỏ dấu, Bờm theo glossary
        scenes = json.loads((self.out / 'de.scenes.json').read_text())
        self.assertIn('Frau Mận sprach mit Bờm.', [s['paragraph'] for s in scenes])
        (self.out / 'de.md').write_text('sửa tay')
        with self.assertRaises(ValueError):
            prep_translation(self.out, 'de')

    def test_prep_translation_rejects_failed_review(self):
        from karma.cli_prep import prep_translation
        self.run_with(Fake(review_scores={('Beta', False): 5, ('Beta', True): 5}))
        with self.assertRaises(ValueError):
            prep_translation(self.out, 'de')

    def test_vi_grade_warning(self):
        self.assertIn('Chưa chấm', tr.vi_grade_status(self.source))
        score = self.source.with_name(self.source.name + '.score.json')
        score.write_text(json.dumps({'pass': True, 'score': 8.5, 'source_sha': tr.sha(SOURCE)}))
        self.assertEqual(tr.vi_grade_status(self.source), '')
        self.source.write_text(SOURCE + 'thêm\n', encoding='utf-8')
        self.assertIn('đã sửa', tr.vi_grade_status(self.source))

    def test_source_outside_target_length_is_rejected_before_any_call(self):
        cfg = json.loads((self.root / 'config.json').read_text())
        cfg['target_minutes'] = [30, 40]
        (self.root / 'config.json').write_text(json.dumps(cfg))
        fake = Fake()
        with self.assertRaises(ValueError) as error:
            self.run_with(fake)
        self.assertEqual(fake.calls, [])
        self.assertIn('ngoài khoảng 30–40', str(error.exception))
        self.run_with(fake, ignore_length=True)      # cho phép bỏ qua có chủ ý
        review = json.loads((self.out / 'de.review.json').read_text())
        self.assertFalse(review['pass'])             # bản dịch vẫn bị đánh trượt vì quá ngắn
        self.assertFalse(review['length']['ok'])

    def test_estimate_for_story_017_v3_is_in_range(self):
        cfg = {'target_minutes': [30, 40], 'words_per_minute': {}}
        self.assertTrue(30 <= tr.estimate_minutes('tiếng ' * 5001, 'en', cfg) <= 40)

    def test_glossary_only_stops_early(self):
        fake = Fake()
        self.run_with(fake, glossary_only=True)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue((self.out / 'glossary.de.md').exists())


if __name__ == '__main__':
    unittest.main()
