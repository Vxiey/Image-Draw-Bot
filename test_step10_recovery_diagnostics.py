import json, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image

import SessionRecovery as SR
import DiagnosticsPackage as DP
from Version import APP_VERSION, FILE_VERSION

class Step10Tests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_recovery_snapshot_never_restores_armed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); state=base/'recovery'/'session-recovery.json'; image=base/'recovery'/'last-image.png'
            with patch.object(SR,'RECOVERY_DIR',state.parent), patch.object(SR,'STATE_FILE',state), patch.object(SR,'IMAGE_FILE',image):
                SR.save_snapshot(profile='Microsoft Paint',options={'quality':'High detail','preview_mode':'Auto full'},saved_area=[(1,2),(30,40)],image=Image.new('RGBA',(8,6),'red'))
                loaded=SR.load_snapshot()
                self.assertTrue(loaded['has_image']);self.assertEqual(loaded['profile'],'Microsoft Paint')
                raw=json.loads(state.read_text())
                self.assertFalse(raw['safety']['drawing_armed'])
                self.assertFalse(raw['safety']['target_lock_restored'])
                self.assertEqual(SR.load_cached_image().size,(8,6))

    def test_clear_recovery_removes_cached_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); state=base/'session-recovery.json'; image=base/'last-image.png'
            state.write_text('{}');Image.new('RGB',(2,2)).save(image)
            with patch.object(SR,'RECOVERY_DIR',base),patch.object(SR,'STATE_FILE',state),patch.object(SR,'IMAGE_FILE',image):
                SR.clear_snapshot();self.assertFalse(state.exists());self.assertFalse(image.exists())

    def test_diagnostics_excludes_recovery_image_and_sanitizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);(base/'logs').mkdir();(base/'logs'/'ImageDrawBot-session.log').write_text(r'path=C:\Users\Felix\Desktop\secret.png token=abc123')
            (base/'settings.json').write_text(json.dumps({'quality':'High detail','corners':[[1,2],[3,4]]}))
            out=base/'diag'
            with patch.object(DP,'DIAGNOSTICS_DIR',out),patch.object(DP,'data_dir',lambda:base),patch.object(DP,'diagnostics_summary',lambda:{'available':True,'has_cached_image':True}):
                path=DP.create_diagnostics_package({'profile':'Microsoft Paint'})
                with zipfile.ZipFile(path) as z:
                    names=set(z.namelist());self.assertNotIn('recovery/last-image.png',names)
                    log=z.read('logs/ImageDrawBot-session.log').decode();self.assertNotIn('Felix',log);self.assertNotIn('abc123',log)
                    settings=json.loads(z.read('settings-summary.json'));self.assertNotIn('corners',settings['settings.json'])

if __name__=='__main__':unittest.main()
