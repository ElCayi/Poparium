import datetime as dt
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keepstate import (LOGO_CYCLE, backups_to_keep, fit_figures, month_grid, TEXT_FIELDS, tmux_status, Drafts, Store, logo_frame, commit_graph, from_markdown, load_popo, popo_look, growth, png_bytes, scale_rgba, stamp,
                       to_markdown, version_diff)


class KeepstateStoreTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = Path(self.folder.name) / 'store.db'
        self.store = Store(self.db_path)

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def test_full_lifecycle(self):
        identifier = self.store.create('Revisar cuaderno', 'Quiero ser autónomo',
                                       plan='Abrirlo tres minutos', cue='Al entrar en tmux',
                                       success='Lo consulté', recovery='Revisar disparador')
        self.assertEqual(len(self.store.active()), 1)
        self.store.log(identifier, 'done', 'Mi primer día')
        self.store.log(identifier, 'progress', 'Me acordé sin ayuda')
        self.store.log(identifier, 'obstacle', 'Sin disparador visible')
        self.assertEqual(len(self.store.entries()), 3)
        self.assertEqual(self.store.experience_counts()[identifier]['done'], 1)
        self.store.review(identifier, 'Necesito un hábito existente', 'Poner atajo fijo')
        self.assertEqual(len(self.store.latest_reviews()), 1)
        self.store.update(identifier, status='archived')
        self.assertEqual(len(self.store.active()), 0)
        self.assertEqual(len(self.store.all_commitments()), 1)
        output = self.store.export()
        content = output.read_text(encoding='utf-8')
        self.assertIn('Mi primer día', content)
        self.assertIn('Poner atajo fijo', content)
        self.assertIn('Revisar cuaderno', content)

    def test_db_and_export_are_private_files(self):
        self.assertEqual(self.db_path.stat().st_mode & 0o777, 0o600)
        exported = self.store.export()
        self.assertEqual(exported.stat().st_mode & 0o777, 0o600)

    def test_timestamps_are_utc_so_text_order_is_time_order(self):
        self.assertTrue(stamp().endswith('+00:00'))

    def test_review_returns_the_hash_shown_in_history(self):
        identifier = self.store.create('Revisar cuaderno', 'Quiero ser autónomo')
        commit = self.store.review(identifier, 'Aprendí algo', 'Ajusto algo')
        self.assertRegex(commit, r'^[0-9a-f]{7}$')
        history = self.store.history()
        self.assertEqual([e['kind'] for e in history], ['review', 'init'])
        self.assertEqual(history[0]['hash'], commit)
        self.assertEqual(self.store.history()[0]['hash'], commit)
        self.assertIn(commit, self.store.export().read_text(encoding='utf-8'))

    def test_graph_gives_each_commitment_its_own_lane(self):
        a = self.store.create('A', 'porque A')
        b = self.store.create('B', 'porque B')
        self.store.review(a, 'aprendí A', '')
        self.store.review(b, 'aprendí B', '')
        # Everything was created in the same second: spread it over days, oldest first
        for row, day in ((a, 1), (b, 2)):
            self.store.db.execute("UPDATE commitments SET created_at=? WHERE id=?", (f"2026-10-0{day}T00:00:00+00:00", row))
        self.store.db.execute("UPDATE reviews SET created_at='2026-10-03T00:00:00+00:00' WHERE commitment_id=?", (a,))
        self.store.db.execute("UPDATE reviews SET created_at='2026-10-04T00:00:00+00:00' WHERE commitment_id=?", (b,))
        rows = commit_graph(self.store.history())
        drawn = [''.join(ch for ch, _ in top) + ' ' + e['message'] for top, _, _, e in rows]
        self.assertEqual(drawn, ['* aprendí B', '│* aprendí A', '*│ init · B', ' * init · A'])
        self.assertEqual([head for _, _, head, _ in rows], [True, True, False, False])

    def test_popo_is_always_glad_and_grows_with_experiences(self):
        a = self.store.create('Revisar cuaderno', 'Quiero ser autónomo')
        item = self.store.all_commitments()[0]
        before = popo_look(item, 0)[0]
        for kind in ('obstacle', 'obstacle', 'obstacle'):
            self.store.log(a, kind, '')
        n = sum(self.store.experience_counts()[a].values())
        self.assertEqual(popo_look(item, n)[0], before)  # obstacles don't change what he does
        self.assertEqual(popo_look(item, n)[1], '3 experiencias')
        self.assertEqual([growth(n) for n in (0, 2, 3, 8, 15, 25, 400)], [0, 0, 1, 2, 3, 4, 4])
        self.store.update(a, status='integrated')
        self.assertEqual(popo_look(self.store.all_commitments()[0], n), ('hello', 'integrado ♡'))

    def test_popo_art_loads_with_whole_frames(self):
        popo = load_popo()
        self.assertIsNotNone(popo)
        self.assertEqual(set(popo['states']), {'idle', 'hello', 'think', 'coding', 'reading', 'sleep', 'comfort'})
        for frames in popo['states'].values():
            self.assertTrue(all(len(f) == popo['size'] ** 2 for f in frames))
        self.assertEqual(len(popo['logo']), 5)
        self.assertEqual({len(row) for frame in popo['logo'] for row in frame}, {12})
        self.assertIsNone(load_popo(Path(self.folder.name) / 'missing.json'))

    def test_markdown_round_trip_keeps_long_text_and_own_headings(self):
        fields = {'title': 'Avisar cuando cambien los planes',
                  'pinned': 'Si cambia un plan compartido, aviso en cuanto lo sé.',
                  'body': '## Por qué me importa · qué hay en juego\n\nNo es pedir permiso.\n\n'
                          '### Lo que pensaba yo\n- No siempre se puede anticipar\n\n## CONCLUSIONES\nSin resolver.'}
        self.assertEqual(from_markdown(to_markdown(fields)), fields)
        self.assertIn('## TITLE', to_markdown(fields))
        # Deleting the NOTA section leaves no note; text right under the title is free text
        self.assertEqual(from_markdown('## TITLE\n\nA\n\nTexto libre\n'), {'title': 'A', 'pinned': '', 'body': 'Texto libre'})
        self.assertEqual(from_markdown('## TITLE\n\nA\n\n---\n\nTexto\n')['body'], 'Texto')
        # Drafts written with older templates still keep their title
        self.assertEqual(from_markdown('# Antiguo\n\n## WHY · x\n\nporque')['title'], 'Antiguo')

    def test_old_notebook_gains_sections_and_a_first_version(self):
        old = Path(self.folder.name) / 'old.db'
        db = sqlite3.connect(old)
        db.executescript("""CREATE TABLE commitments (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            reason TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '', cue TEXT NOT NULL DEFAULT '',
            success TEXT NOT NULL DEFAULT '', recovery TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO commitments (title, reason, created_at, updated_at)
            VALUES ('Antiguo', 'Porque sí', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00');""")
        db.commit()
        db.close()
        store = Store(old)
        try:
            item = store.all_commitments()[0]
            self.assertEqual((item['title'], item['reason'], item['reasoning']), ('Antiguo', 'Porque sí', ''))
            self.assertEqual([v['note'] for v in store.versions(item['id'])], ['Acuerdo inicial'])
            backup = Path(self.folder.name) / 'old.pre-0.2.db'
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(sqlite3.connect(backup).execute('SELECT title FROM commitments').fetchone(), ('Antiguo',))
        finally:
            store.close()

    def test_each_edit_is_a_version_with_its_diff(self):
        identifier = self.store.create('Avisar', 'Coordinarnos')
        self.assertIsNone(self.store.revise(identifier, {'pinned': 'Coordinarnos'}, 'nada'))
        label = self.store.revise(identifier, {'pinned': 'Coordinarnos, no controlar'}, 'Aclarado el motivo')
        self.assertEqual(label, 'v1.1')
        old, new = (v['snapshot'] for v in self.store.versions(identifier))
        self.assertEqual(version_diff(old, new), ['## NOTA', '@@ -1 +1 @@', '-Coordinarnos', '+Coordinarnos, no controlar'])
        self.assertEqual([e['message'] for e in self.store.history()], ['v1.1 · Aclarado el motivo', 'init · Avisar'])
        self.assertIn('v1.1 · ', self.store.export().read_text(encoding='utf-8'))

    def test_drafts_are_private_and_the_autosave_wins(self):
        drafts = Drafts(Path(self.folder.name) / 'store.drafts')
        self.assertEqual(drafts.folder.stat().st_mode & 0o777, 0o700)
        self.assertIsNone(drafts.recover('nuevo'))
        path = drafts.write('nuevo', '# Último :w')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(drafts.recover('nuevo'), '# Último :w')
        # The editor died after more typing: that typing is what comes back
        drafts.autosave_path('nuevo').write_text('# Último :w y algo más', encoding='utf-8')
        self.assertEqual(drafts.recover('nuevo'), '# Último :w y algo más')
        self.assertEqual(drafts.pending(), ['nuevo'])
        drafts.discard('nuevo')
        self.assertEqual((drafts.recover('nuevo'), drafts.pending()), (None, []))

    def test_line_drafts_live_apart_from_documents(self):
        drafts = Drafts(Path(self.folder.name) / 'store.drafts')
        drafts.write('linea-abc', 'a medias', '.txt')
        self.assertEqual(drafts.recover('linea-abc', '.txt'), 'a medias')
        self.assertEqual(drafts.pending(), [])

    def test_logo_breathes_and_only_blinks_now_and_then(self):
        self.assertEqual(logo_frame(0), (0, 1400))
        self.assertEqual(logo_frame(1400)[0], 1)
        # Eyes closed only a tiny part of the time
        closed = sum(1 for t in range(0, LOGO_CYCLE, 10) if logo_frame(t)[0] in (3, 4))
        self.assertLess(closed / (LOGO_CYCLE / 10), 0.05)
        self.assertGreater(LOGO_CYCLE, 15000)

    def test_deleted_entries_and_commitments_can_come_back(self):
        a = self.store.create('Avisar', 'Coordinarnos')
        self.store.log(a, 'done', 'Avisé a tiempo')
        self.store.log(a, 'obstacle', 'Lo olvidé')
        self.store.review(a, 'Aprendí', 'Ajusto')
        self.store.revise(a, {'pinned': 'Coordinarnos mejor'}, 'Aclarado')
        entry = self.store.entries()[0]
        removed = self.store.delete_entry(entry['id'])
        self.assertEqual([e['note'] for e in self.store.entries()], ['Avisé a tiempo'])
        self.store.restore(removed)
        self.assertEqual([e['id'] for e in self.store.entries()][0], entry['id'])
        before = (self.store.history(), [dict(e) for e in self.store.entries()])
        removed = self.store.delete_commitment(a)
        self.assertEqual((self.store.all_commitments(), self.store.entries(), self.store.history()), ([], [], []))
        self.store.restore(removed)
        self.assertEqual((self.store.history(), [dict(e) for e in self.store.entries()]), before)

    def test_tmux_status_shows_only_a_face_and_never_creates_a_notebook(self):
        missing = Path(self.folder.name) / 'nope.db'
        self.assertEqual(tmux_status(missing), '(^ᴗ^)')
        self.assertFalse(missing.exists())
        self.store.create('Secreto que no debe verse', 'porque sí')
        self.assertNotIn('Secreto', tmux_status(self.db_path))
        Drafts(Path(self.folder.name) / 'store.drafts').write('nuevo', 'a medias')
        self.assertTrue(tmux_status(self.db_path).endswith('✎'))

    def test_old_sections_become_free_text_once(self):
        old = Path(self.folder.name) / 'old.db'
        db = sqlite3.connect(old)
        db.executescript("""CREATE TABLE commitments (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            reason TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '', cue TEXT NOT NULL DEFAULT '',
            success TEXT NOT NULL DEFAULT '', recovery TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '', reasoning TEXT NOT NULL DEFAULT '', agreement TEXT NOT NULL DEFAULT '',
            exceptions TEXT NOT NULL DEFAULT '', tracking TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO commitments (title, reason, agreement, cue, tracking, created_at, updated_at)
            VALUES ('Comida', 'Nos sienta bien', 'Aviso si me retraso', 'Al mediodía', 'periodic',
                    '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00');""")
        db.commit()
        db.close()
        store = Store(old)
        try:
            item = store.all_commitments()[0]
            self.assertEqual(item['pinned'], 'Aviso si me retraso')
            self.assertIn('## Por qué me importa\n\nNos sienta bien', item['body'])
            self.assertIn('## Desencadenantes\n\nAl mediodía', item['body'])
            self.assertIn('periódico', item['body'])
            self.assertEqual(item['reason'], 'Nos sienta bien')  # the old column is kept
            self.assertTrue((Path(self.folder.name) / 'old.pre-0.3.db').exists())
            # The old v1.0 reads as the new document: an edit diffs only what changed
            store.revise(1, {'pinned': 'Aviso si me retraso, siempre'}, 'Matiz')
            old_v, new_v = (v['snapshot'] for v in store.versions(1))
            self.assertEqual(version_diff(old_v, new_v)[0], '## NOTA')
            self.assertEqual(len([l for l in version_diff(old_v, new_v) if l.startswith('## ')]), 1)
            # Once only: emptying the text later doesn't bring the old sections back
            store.revise(1, {'body': ''}, 'Limpio')
        finally:
            store.close()
        store = Store(old)
        try:
            self.assertEqual(store.all_commitments()[0]['body'], '')
        finally:
            store.close()

    def test_entries_remember_the_version_in_force(self):
        a = self.store.create('Avisar', 'Coordinarnos')
        self.store.log(a, 'done', 'antes')
        self.store.revise(a, {'pinned': 'Coordinarnos mejor'}, 'Aclarado')
        self.store.log(a, 'done', 'después')
        self.store.review(a, 'Aprendí', '')
        v0, v1 = (v['id'] for v in self.store.versions(a))
        rows = self.store.db.execute("SELECT note, version_id FROM journal ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [('antes', v0), ('después', v1)])
        self.assertEqual(self.store.db.execute("SELECT version_id FROM reviews").fetchone()[0], v1)

    def test_old_entries_get_the_version_that_was_in_force_then(self):
        old = Path(self.folder.name) / 'old.db'
        db = sqlite3.connect(old)
        db.executescript("""CREATE TABLE commitments (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
            reason TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '', cue TEXT NOT NULL DEFAULT '',
            success TEXT NOT NULL DEFAULT '', recovery TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE journal (id INTEGER PRIMARY KEY, commitment_id INTEGER NOT NULL, kind TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
            INSERT INTO commitments (title, reason, created_at, updated_at)
            VALUES ('Antiguo', 'Porque sí', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00');
            INSERT INTO journal (commitment_id, kind, note, created_at) VALUES (1, 'done', 'hecho', '2026-10-02T00:00:00+00:00');""")
        db.commit()
        db.close()
        store = Store(old)
        try:
            v0 = store.versions(1)[0]['id']
            self.assertEqual(store.db.execute("SELECT version_id FROM journal").fetchone()[0], v0)
        finally:
            store.close()

    def test_calendar_groups_by_local_day_and_weeks_start_on_monday(self):
        a = self.store.create('Avisar', 'Coordinarnos')
        self.store.log(a, 'obstacle', 'hoy')
        today = dt.date.today()
        events = self.store.events_between(today, today)
        self.assertEqual({(e['kind'], e['day']) for e in events}, {('init', today), ('obstacle', today)})
        self.assertEqual(self.store.events_between(today + dt.timedelta(days=1), today + dt.timedelta(days=2)), [])
        weeks = month_grid(dt.date(2026, 10, 11))
        self.assertEqual((weeks[0][0], weeks[-1][-1], len(weeks)), (dt.date(2026, 9, 28), dt.date(2026, 11, 1), 5))
        self.assertTrue(all(w[0].weekday() == 0 for w in weeks))

    def test_obstacles_can_be_repaired_later(self):
        a = self.store.create('Avisar', 'Coordinarnos')
        self.store.log(a, 'obstacle', '')  # an empty note is fine: it happened
        entry = self.store.entries()[0]
        self.store.repair(entry['id'], 'Pedí perdón y avisé')
        self.assertEqual(self.store.entries()[0]['repair'], 'Pedí perdón y avisé')
        self.assertEqual(self.store.recent(commitment_id=a)[0]['repair'], 'Pedí perdón y avisé')

    def test_logging_another_day_keeps_the_version_of_that_day(self):
        a = self.store.create('Avisar', 'Coordinarnos')
        self.store.db.execute("UPDATE versions SET created_at='2026-10-01T00:00:00+00:00'")
        self.store.revise(a, {'pinned': 'Coordinarnos mejor'}, 'Aclarado')
        v0, v1 = (v['id'] for v in self.store.versions(a))
        self.store.log(a, 'done', 'me acordé tarde', when='2026-10-03T12:00:00+00:00')
        self.store.log(a, 'done', 'hoy')
        rows = self.store.db.execute("SELECT note, version_id, created_at FROM journal ORDER BY id").fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [('me acordé tarde', v0), ('hoy', v1)])
        self.assertTrue(rows[0][2].startswith('2026-10-03'))

    def test_integrated_commitments_stay_in_the_list(self):
        a = self.store.create('A', 'x')
        b = self.store.create('B', 'y')
        self.store.update(a, status='integrated')
        self.store.update(b, status='archived')
        self.assertEqual([c['title'] for c in self.store.active()], ['A'])

    def test_popo_png_is_a_real_png_of_the_right_size(self):
        raw = bytes([255, 0, 0, 255] * 4)  # 2x2 red
        rows = scale_rgba(raw, 2, 2, 5, 3)
        self.assertEqual((len(rows), len(rows[0])), (3, 5 * 4))
        png = png_bytes(5, 3, rows)
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(int.from_bytes(png[16:20], 'big'), 5)

    def test_figures_shorten_their_names_before_breaking_the_box(self):
        figures = [(1, 'ACUERDOS', 'ACU', 'a'), (0, 'EXPERIENCIAS', 'EXP', 'good'),
                   (0, 'DESCUBRIMIENTOS', 'DESC', 'b'), (0, 'INTEGRADOS', 'INT', 'warm')]
        for width in range(10, 120):
            rows = fit_figures(figures, width)
            for row in rows:
                col, number, name, _ = row[-1]
                self.assertLessEqual(col + 3 + len(name), max(width, 3 + len('DESC')))
        self.assertEqual([c[2] for c in fit_figures(figures, 90)[0]], ['ACUERDOS', 'EXPERIENCIAS', 'DESCUBRIMIENTOS', 'INTEGRADOS'])
        self.assertEqual([c[2] for c in fit_figures(figures, 40)[0]], ['ACU', 'EXP', 'DESC', 'INT'])
        self.assertEqual(len(fit_figures(figures, 20)), 2)

    def test_daily_backups_are_private_and_pruned(self):
        self.assertIsNone(self.store.daily_backup())  # nothing to copy yet
        self.store.create('Avisar', 'Coordinarnos')
        today = dt.date(2026, 10, 11)
        first = self.store.daily_backup(today)
        self.assertEqual(first.stat().st_mode & 0o777, 0o600)
        self.assertEqual(first.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(sqlite3.connect(first).execute('SELECT title FROM commitments').fetchone(), ('Avisar',))
        self.assertEqual(self.store.daily_backup(today), first)  # once a day
        for days in range(1, 400):
            self.store.daily_backup(today + dt.timedelta(days=days))
        kept = sorted(first.parent.glob('*.db'))
        self.assertLessEqual(len(kept), 14 + 12)
        self.assertTrue(any('2027-11-14' in f.name for f in kept))  # the newest

    def test_backups_keep_two_weeks_and_a_year_of_months(self):
        today = dt.date(2026, 10, 11)
        dates = {today - dt.timedelta(days=n) for n in range(500)}
        keep = backups_to_keep(dates, today)
        self.assertTrue({today - dt.timedelta(days=n) for n in range(14)} <= keep)
        self.assertNotIn(today - dt.timedelta(days=20), keep)
        months = {(d.year, d.month) for d in keep}
        self.assertEqual(len(months), 12)


if __name__ == '__main__':
    unittest.main()
