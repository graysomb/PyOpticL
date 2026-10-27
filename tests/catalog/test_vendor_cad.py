import hashlib
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyOpticL import vendor_cad as cad

STEP=b"ISO-10303-21;\nHEADER;FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));ENDSEC;DATA;ENDSEC;END-ISO-10303-21;"
class DownloadTests(unittest.TestCase):
    def test_missing_asset_identifies_the_part_and_cache_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            record=cad.register('thorlabs','KA05TA','https://www.thorlabs.com/item/KA05TA',STEP,'KA05TA.step','step',root=root)
            cad.resolve(record,root).unlink()
            with self.assertRaisesRegex(FileNotFoundError,'Missing pinned CAD asset for KA05TA.*PYOPTICL_CAD_CACHE'):
                cad.resolve(record,root)

    def test_cache_validation_and_revision(self):
        with tempfile.TemporaryDirectory() as root:
            r=cad.register('thorlabs','KA05TA','https://www.thorlabs.com/item/KA05TA',STEP,'KA05TA.step','step',root=root)
            path=cad.resolve(r,root)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),r['sha256'])
            newer=cad.register('thorlabs','KA05TA',r['product_url'],STEP+b'\n','KA05TA.step','step',root=root)
            self.assertNotEqual(r['sha256'],newer['sha256'])
            path.write_bytes(b'broken')
            with self.assertRaises(ValueError):cad.resolve(r,root)

    def test_cli_refuses_repinning(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            record=cad.register('thorlabs','KA05TA','https://www.thorlabs.com/item/KA05TA',STEP,'KA05TA.step','step',root=root)
            manifest=root/'pin.json';manifest.write_text(json.dumps(record))
            source=root/'KA05TA.step';source.write_bytes(STEP+b'\n')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                cad.main(['register','--vendor','thorlabs','--part','KA05TA',
                          '--product-url',record['product_url'],'--kind','step',
                          '--file',str(source),'--manifest',str(manifest),'--cache',str(root)])
            self.assertEqual(failure.exception.code,1)
            self.assertEqual(json.loads(manifest.read_text())['sha256'],record['sha256'])

    def test_bad_downloads_and_identity(self):
        for kind in ['step','pdf']:
            for data in [b'',b'<html>sign in</html>',b'%PDF-1.7 truncated']:
                with self.assertRaises(ValueError):cad.validate(data,kind)
        with self.assertRaises(ValueError):cad.check_url('thorlabs','https://thorlabs.com.evil.test/a')
        with self.assertRaises(ValueError):cad.register('thorlabs','KA05TA','https://www.thorlabs.com/item/KA05TA',STEP,'other.step','step')

    def test_vendor_handlers_and_dynamic_fallback(self):
        for vendor,url,part in [('thorlabs','https://www.thorlabs.com/item/KA05TA','KA05TA'),('optosigma','https://www.optosigma.com/us_en/TSDH-251S.html','TSDH-251S')]:
            page=('<a href="/'+part+'.step">CAD</a>').encode()
            with patch.object(cad,'fetch',return_value=(page,url)):
                self.assertEqual(cad.discover(vendor,part,url)[0]['kind'],'step')
            with patch.object(cad,'fetch',return_value=(b'<div>dynamic</div>',url)):
                with self.assertRaises(cad.BrowserRequired):cad.discover(vendor,part,url)

if __name__=='__main__':unittest.main()
