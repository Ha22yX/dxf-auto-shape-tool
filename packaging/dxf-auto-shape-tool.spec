# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import runpy
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH).parent
app_version = runpy.run_path(str(project_root / 'backend' / 'version.py'))['APP_VERSION']
build_name = f'dxf-auto-shape-tool-v{app_version}'
version_tuple = tuple(int(part) for part in app_version.split('.')) + (0,)
version_file = project_root / 'build' / 'version-info.txt'
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(f'''VSVersionInfo(
    ffi=FixedFileInfo(filevers={version_tuple!r}, prodvers={version_tuple!r},
        mask=0x3f, flags=0, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'Ha22yX'),
        StringStruct('FileDescription', 'DXF Auto Shape Tool'),
        StringStruct('FileVersion', '{app_version}'),
        StringStruct('InternalName', 'DXF-Auto-Shape-Tool'),
        StringStruct('OriginalFilename', '{build_name}.exe'),
        StringStruct('ProductName', 'DXF Auto Shape Tool'),
        StringStruct('ProductVersion', '{app_version}')
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)''', encoding='utf-8')
datas = [(str(project_root / 'frontend'), 'frontend'), (str(project_root / 'LICENSE'), '.')]
binaries = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on']
hiddenimports += collect_submodules('backend')
tmp_ret = collect_all('ezdxf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('shapely')
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
    name=build_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
