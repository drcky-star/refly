# PyInstaller spec — Refly masaüstü uygulaması (.app / .exe)
# Kurulum: ./venv/bin/pip install pyinstaller
# Derle:   ./venv/bin/pyinstaller refly-desktop.spec
# Çıktı:   dist/Refly.app (macOS) — çift tıkla çalışır, yerel pencerede açılır.

block_cipher = None

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/templates', 'app/templates'),
        ('app/static', 'app/static'),
        ('app/csl', 'app/csl'),
    ],
    hiddenimports=['citeproc', 'citeproc_styles', 'anthropic', 'webview'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Refly',
          debug=False, strip=False, upx=True, console=False)

coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=True, name='Refly')

app = BUNDLE(coll, name='Refly.app', icon='app/static/refly.icns',
             bundle_identifier='com.refly.app',
             info_plist={'NSHighResolutionCapable': True})
