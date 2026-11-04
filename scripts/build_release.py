"""Build a source release from explicit allowlists; never package user data."""
import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.10.0'
NAME=f'GongkaoTutor-v{VERSION}'
ROOT_FILES=['.gitignore','.gitattributes','README.md','LICENSE','CHANGELOG.md','THIRD_PARTY_NOTICES.md',
    'requirements.txt','requirements-dev.txt','requirements-tested.txt',
    'install-dependencies.ps1','service.ps1','start.ps1','首次安装.cmd','启动知序.cmd','停止知序.cmd']
DOCS=['docs/INSTALL.md','docs/USER_GUIDE.md','docs/DATA_AND_PRIVACY.md','docs/ARCHITECTURE.md',
    'docs/images/calculation-training.png']
BLOCKED_PARTS={'data','work','.venv','.git','__pycache__','.ocr-cache','page-overrides','node_modules'}
BLOCKED_SUFFIXES={'.sqlite','.sqlite3','.db','.pem','.key','.pfx','.log','.pyc','.pdf','.docx','.xlsx'}
PATTERNS={
    'api_token':re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b'),
    'github_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'personal_windows_path':re.compile(r'[A-Za-z]:[\\/]Users[\\/][^\s<>"\n/\\]+[\\/]'),
}


def sha(data):return hashlib.sha256(data).hexdigest()


def source_paths():
    paths=[Path(s) for s in ROOT_FILES+DOCS]
    paths+=sorted(p.relative_to(ROOT) for p in ROOT.glob('*.py'))
    paths+=sorted(p.relative_to(ROOT) for p in (ROOT/'web').glob('*') if p.is_file())
    paths+=sorted(p.relative_to(ROOT) for p in (ROOT/'tests').glob('test_*.py'))
    paths += [Path('samples/questions.json'),Path('samples/knowledge.md'),Path('scripts/build_release.py')]
    vendor=ROOT/'vendor/shenlun-master'
    manifest=json.loads((vendor/'manifest.json').read_text('utf-8'))
    paths += [Path('vendor/shenlun-master')/item['path'] for item in manifest['files']]
    paths += [Path('vendor/shenlun-master/manifest.json'),Path('vendor/shenlun-master/NOTICE.md')]
    return sorted(set(paths),key=lambda p:p.as_posix())


def check_path(rel):
    if rel.is_absolute() or '..' in rel.parts or any(p in BLOCKED_PARTS for p in rel.parts):
        raise ValueError('Forbidden release path: '+rel.as_posix())
    if rel.suffix.lower() in BLOCKED_SUFFIXES or rel.name.startswith('.env'):
        raise ValueError('Forbidden release file: '+rel.as_posix())
    p=ROOT/rel
    if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(ROOT):
        raise ValueError('Missing or linked release file: '+rel.as_posix())


def scan(rel,data):
    if rel.suffix.lower()=='.png':
        if rel.as_posix()!='docs/images/calculation-training.png':raise ValueError('Unapproved image')
        return []
    value=data.decode('utf-8-sig')
    return [{'file':rel.as_posix(),'line':value[:m.start()].count('\n')+1,'pattern':label}
        for label,pattern in PATTERNS.items() for m in pattern.finditer(value)]


def check_vendor():
    root=ROOT/'vendor/shenlun-master'
    manifest=json.loads((root/'manifest.json').read_text('utf-8'))
    for item in manifest['files']:
        if sha((root/item['path']).read_bytes())!=item['sha256']:
            raise ValueError('Vendor checksum mismatch: '+item['path'])
    return {'repository':manifest['repository'],'commit':manifest['commit'],'verified_files':len(manifest['files'])}


def build(destination):
    destination=destination.resolve();destination.mkdir(parents=True,exist_ok=True)
    stage=destination/NAME;archive=destination/(NAME+'-source.zip')
    if stage.exists() or archive.exists():raise ValueError('Output exists. Choose a new --output directory to preserve it.')
    paths=source_paths();findings=[];contents={};vendor=check_vendor()
    for rel in paths:
        check_path(rel);data=(ROOT/rel).read_bytes();findings+=scan(rel,data)
        if rel.suffix.lower() in ('.ps1','.cmd'):
            encoding='utf-8-sig' if rel.suffix.lower()=='.ps1' else 'utf-8'
            data=data.decode('utf-8-sig').replace('\r\n','\n').replace('\n','\r\n').encode(encoding)
        contents[rel.as_posix()]=data
    if findings:raise ValueError('Sensitive-pattern findings; no release created: '+json.dumps(findings,ensure_ascii=False))
    manifest={'project':'GongkaoTutor','version':VERSION,'release_candidate_date':'2026-11-04',
        'scope':'Source, original samples, public documentation and attributed vendor rules only.',
        'excludes':['user data','credentials','uploaded materials','OCR weights','caches','local logs','Python runtimes'],
        'vendor':vendor,'manifest_note':'This manifest does not hash itself.',
        'files':[{'path':name,'bytes':len(data),'sha256':sha(data)} for name,data in contents.items()]}
    contents['MANIFEST.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    stage.mkdir()
    for name,data in contents.items():
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(contents.items()):
            info=zipfile.ZipInfo(NAME+'/'+name,date_time=(2026,11,4,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,data)
    archive_hash=sha(archive.read_bytes())
    checksum=destination/(archive.name+'.sha256')
    checksum.write_text(archive_hash+'  '+archive.name+'\n','ascii')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert set(z.namelist())=={NAME+'/'+name for name in contents}
        for name,data in contents.items():assert z.read(NAME+'/'+name)==data
    audit={'version':VERSION,'files_including_manifest':len(contents),'archive_bytes':archive.stat().st_size,
        'sha256':archive_hash,'sensitive_pattern_findings':findings,'vendor_checksums':vendor,
        'scope':'No live user data or configuration copied; candidate awaits user approval before upload.',
        'proposed_github':{'repository':'Jarry-Zhou/GongkaoTutor','visibility':'public','license':'MIT'},
        'stage':str(stage),'archive':str(archive),'checksum':str(checksum)}
    (destination/(NAME+'-audit.json')).write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(audit,ensure_ascii=False,indent=2))
    return stage,archive


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    build(parser.parse_args().output)
