"""Run all offline Python regression tests. Browser acceptance is separate."""
from pathlib import Path
import subprocess,sys
tests=sorted(p for p in Path(__file__).resolve().parent.glob('tests*.py') if p.name not in ('tests_browser.py','tests_ui_fixture.py'))
failed=[]
for path in tests:
    result=subprocess.run([sys.executable,'-X','utf8',str(path)],cwd=path.parent)
    if result.returncode:failed.append(path.name)
print(f"{len(tests)-len(failed)}/{len(tests)} Python test programs passed")
if failed:print('Failed:',', '.join(failed))
sys.exit(bool(failed))
