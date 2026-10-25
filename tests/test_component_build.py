import hashlib,json,pathlib,subprocess,sys,tempfile,unittest,zipfile
class ComponentBuildTest(unittest.TestCase):
 def test_package_and_standard_library_launcher(self):
  root=pathlib.Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory(prefix='decrypthub-component-test-') as directory:
   subprocess.run([sys.executable,str(root/'scripts/build_component.py'),'--output',directory],check=True,capture_output=True)
   archive=next(pathlib.Path(directory).glob('*.zip'))
   with zipfile.ZipFile(archive) as bundle:
    manifest=json.loads(bundle.read('component.json'))
    self.assertEqual(manifest['runtime'],'python');self.assertEqual(manifest['platform'],'any')
    self.assertEqual(set(bundle.namelist()),{'component.json'}|{f['path'] for f in manifest['files']})
    for file in manifest['files']:
     data=bundle.read(file['path']);self.assertEqual(len(data),file['size']);self.assertEqual(hashlib.sha256(data).hexdigest(),file['sha256'])
    bundle.extractall(pathlib.Path(directory)/'installed')
   result=subprocess.run([sys.executable,str(pathlib.Path(directory)/'installed/launch.py'),'--version'],check=True,capture_output=True,text=True)
   self.assertIn(manifest['version'],result.stdout)
if __name__=='__main__':unittest.main()
