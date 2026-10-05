"""Local Git history restricted to project source files, never runtime data."""
import subprocess
import sys
from pathlib import Path
from .project_storage import documents


class ProjectGit:
    def __init__(self, project):
        self.project = project
        self.root = project.root.resolve()

    def run(self, *args):
        result = subprocess.run(['git','--literal-pathspecs','-C',str(self.root),*args],capture_output=True,text=True,encoding='utf-8',
            errors='replace',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        if result.returncode:
            raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Error de Git')
        return result.stdout

    def enabled(self):
        return (self.root/'.git').exists()

    def initialize(self):
        if not self.enabled(): self.run('init')
        ignore = self.root/'.gitignore'
        text = ignore.read_text(encoding='utf-8') if ignore.exists() else ''
        for line in ('/runtime/','/.abscada-save-*/','/.abscada-recovery-*/','/.abscada-save.lock','__pycache__/','*.pyc'):
            if line not in text.splitlines(): text += '\n'+line+'\n'
        ignore.write_text(text,encoding='utf-8')
        self.commit('Proyecto inicial')

    def commit(self, message='Guardar proyecto'):
        if not self.enabled(): return None
        paths = set(documents(self.project)) | {'.gitignore'}
        paths.update(p.relative_to(self.root).as_posix() for p in (self.root/'assets').rglob('*') if p.is_file() and not p.is_symlink())
        tracked = self.run('ls-files','-z').split('\0')
        if 'libraries.json' in tracked:
            paths.add('libraries.json')
        paths.update(p for p in tracked if p.startswith(('screens/','faceplates/','scripts/','assets/')))
        paths = sorted(p for p in paths if (self.root/p).exists() or p in tracked)
        self.run('add','-A','--',*paths)
        if not self.run('diff','--cached','--name-only','--',*paths).strip(): return None
        # --only excludes unrelated staged files from the project snapshot.
        self.run('-c','user.name=abSCADA','-c','user.email=abscada@localhost',
                 'commit','--only','-m',message,'--',*paths)
        return self.run('rev-parse','--short','HEAD').strip()

    def history(self):
        if not self.enabled(): return 'Control de versiones desactivado'
        return self.run('log','-30','--date=local','--format=%h  %ad  %s')

    def diff(self):
        return self.run('diff','HEAD','--',*sorted(set(documents(self.project)) | {'libraries.json'})) if self.enabled() else ''
