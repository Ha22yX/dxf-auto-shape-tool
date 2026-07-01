# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import re

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH).parent
version_file = project_root / 'packaging' / 'version-info.txt'
version_text = version_file.read_text(encoding='utf-8')
version_match = re.search(r"StringStruct\(u'ProductVersion', u'([^']+)'\)", version_text)
app_version = version_match.group(1) if version_match else 'dev'

datas = [(str(project_root / 'frontend'), 'frontend')]
binaries = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on']
hiddenimports += collect_submodules('backend')
tmp_ret = collect_all('ezdxf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(project_root / 'launcher.py')],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'DXF自动图形工具-{app_version}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(project_root / 'frontend' / 'assets' / 'app-icon.ico'),
    version=str(version_file),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
