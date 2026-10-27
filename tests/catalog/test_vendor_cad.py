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
    def test_default_registration_is_versioned_and_resolves_without_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Path(directory)/'sources'
            with patch.dict('os.environ',{},clear=True),patch.object(cad,'source_root',return_value=store), \
                    patch.object(cad,'cache_root',side_effect=AssertionError('No cache access')):
                record=cad.register('thorlabs','KA05TA','https://www.thorlabs.com/item/KA05TA',STEP,'KA05TA.step','step')
                self.assertEqual(cad.resolve(record),(store/record['cache_path']).resolve())

    def test_repository_is_authoritative_and_explicit_root_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            store,cache=Path(directory)/'sources',Path(directory)/'cache'
            record=cad.register('thorlabs','KA05TA','https://www.thorlabs.com/item/KA05TA',STEP,'KA05TA.step','step',root=store)
            cad.register('thorlabs','KA05TA',record['product_url'],STEP,'KA05TA.step','step',root=cache)
            with patch.object(cad,'source_root',return_value=store), \
                    patch.object(cad,'cache_root',side_effect=AssertionError('Do not fall back')):
                self.assertEqual(cad.resolve(record),(store/record['cache_path']).resolve())
                (store/record['cache_path']).write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError,'hash differs'):cad.resolve(record)
                self.assertEqual(cad.resolve(record,cache),(cache/record['cache_path']).resolve())

    def test_legacy_cache_fallback_and_missing_source_error(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)/'cache'
            record=cad.register('thorlabs','KA05TA','https://www.thorlabs.com/item/KA05TA',STEP,'KA05TA.step','step',root=cache)
            with patch.object(cad,'source_root',return_value=Path(directory)/'sources'), \
                    patch.object(cad,'cache_root',return_value=cache):
                self.assertEqual(cad.resolve(record),(cache/record['cache_path']).resolve())
                (cache/record['cache_path']).unlink()
                with self.assertRaisesRegex(FileNotFoundError,'restore catalog_data/sources'):cad.resolve(record)

    def test_paths_cannot_escape_either_store(self):
        with tempfile.TemporaryDirectory() as directory:
            outside=Path(directory)/'outside.step';outside.write_bytes(STEP)
            store=Path(directory)/'sources';store.mkdir()
            for key in ('../outside.step',str(outside)):
                with self.assertRaisesRegex(ValueError,'escapes'):
                    cad.resolve(dict(schema_version=1,cache_path=key),store)
            (store/'linked.step').symlink_to(outside)
            with self.assertRaisesRegex(ValueError,'escapes'):
                cad.resolve(dict(schema_version=1,cache_path='linked.step'),store)

    def test_complete_catalog_is_bundled_and_offline(self):
        with patch.object(cad,'cache_root',side_effect=AssertionError('No cache required')), \
                patch.object(cad,'urlopen',side_effect=AssertionError('No network required')):
            summary=cad.verify_catalog()
            self.assertEqual(summary['records'],42)
            self.assertEqual(summary['files'],41)
            self.assertEqual(summary['bytes'],186896893)
            self.assertTrue(cad.resolve_reference('alignment-iris').is_relative_to(cad.source_root()))
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(cad.main(['verify','--all']),0)

    def test_complete_catalog_check_cannot_be_satisfied_by_external_cache(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(cad,'source_root',return_value=Path(directory)), \
                patch.object(cad,'cache_root',side_effect=AssertionError('Bundled-only verification')):
            with self.assertRaises(FileNotFoundError):cad.verify_catalog()

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
