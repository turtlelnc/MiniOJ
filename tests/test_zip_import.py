import io,stat,unittest,zipfile
from minioj.zip_import import import_cases,ZipImportError

def archive(entries):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in entries:z.writestr(name,value)
    return data.getvalue()
class ZipImportTests(unittest.TestCase):
    def test_named_nested_pairs(self):
        cases=import_cases(archive([('组一/apple.out','3\n'),('组一/apple.in','1 2\n'),('beta.in',''),('beta.out',''),('__MACOSX/noise','x'),('readme.txt','ignored')]))
        self.assertEqual([c['name'] for c in cases],['beta','组一/apple'])
        self.assertEqual(cases[1]['input'],'1 2\n');self.assertEqual(cases[0]['expected_output'],'')
    def test_missing_pair(self):
        with self.assertRaisesRegex(ZipImportError,'缺少 .out'): import_cases(archive([('abc.in','x')]))
    def test_duplicate(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore');payload=archive([('a.in','1'),('a.in','2'),('a.out','3')])
        with self.assertRaisesRegex(ZipImportError,'重复'):import_cases(payload)
    def test_traversal_and_absolute(self):
        for name in ['../a.in','/a.in','folder/../a.in','C:/a.in','folder\\a.in']:
            with self.subTest(name=name),self.assertRaises(ZipImportError):import_cases(archive([(name,'x')]))
    def test_symlink(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            info=zipfile.ZipInfo('a.in');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,'/etc/passwd')
        with self.assertRaisesRegex(ZipImportError,'符号链接'):import_cases(data.getvalue())
    def test_size_limits(self):
        with self.assertRaises(ZipImportError):import_cases(archive([('a.in','x'*131073),('a.out','x')]))
        with self.assertRaises(ZipImportError):import_cases(archive([(f'{i}.{ext}','x'*65537) for i in range(9) for ext in ['in','out']]))
    def test_count_limit(self):
        with self.assertRaisesRegex(ZipImportError,'100'):import_cases(archive([(f'{i}.{ext}','') for i in range(101) for ext in ['in','out']]))
    def test_invalid_utf8_and_zip(self):
        for payload in [b'not zip',archive([('a.in',b'\xff'),('a.out','')]),archive([('readme.txt','empty')])]:
            with self.assertRaises(ZipImportError):import_cases(payload)
