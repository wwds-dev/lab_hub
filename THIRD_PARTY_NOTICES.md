# Third-party notices

Lab Hub contains or uses the open-source components below. Licence names come from the packages' own metadata, read on
2026-11-17 for the build listed at the end. The full licence text of each component is in its own project (links) and, where the
package ships it, in its `*.dist-info/licenses` folder; copies of the texts named in each section must travel with the app.
This file is a notice, not a grant: the licence of Lab Hub itself is stated in `LICENSE`.

## Qt and PySide6 (LGPL-3.0)

Lab Hub uses **Qt 6.12** through **PySide6 / Shiboken6 6.12.0** (Qt for Python), including Qt WebEngine and Qt PDF.
Copyright (C) The Qt Company Ltd. and other contributors. Qt and PySide6 are used here under the **GNU Lesser General Public
License, version 3** (LGPL-3.0), with the GNU GPL version 3 that it incorporates.
Lab Hub is not affiliated with or endorsed by The Qt Company.

- Qt is linked **dynamically**. In the macOS app the Qt libraries are separate frameworks and files inside
  `Lab Hub.app/Contents/Frameworks/PySide6/Qt/lib/` and `Lab Hub.app/Contents/Resources/PySide6/`. You may replace them with a
  modified or different version of Qt 6 / PySide6 and run Lab Hub with it. Lab Hub's terms do not forbid modifying Qt or
  reverse engineering the app to debug such changes.
- **To replace Qt in the installed app:** put your Qt frameworks and PySide6 modules in place of the files above, then re-sign the
  bundle (macOS refuses to run an altered ad-hoc bundle): `codesign --force --deep -s - "/Applications/Lab Hub.app"`.
- **To rebuild Lab Hub with another Qt/PySide6:** clone the repository, create a virtualenv, install your PySide6 build
  (`pip install PySide6==<version>` or your own wheel), then run `./build_app.sh` (PyInstaller, onedir `.app`).
- **Corresponding source** for the exact version shipped (unmodified), from the Qt Project:
  - PySide6 6.12.0 (Qt for Python): https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/ and
    https://code.qt.io/cgit/pyside/pyside-setup.git/ (tag `v6.12.0`)
  - Qt 6.12.0 (including Qt WebEngine): https://download.qt.io/official_releases/qt/6.12/6.12.0/single/
  - Lab Hub's maintainer will also attach copies of these archives to the GitHub release of any binary he publishes (to do).
- Texts: GNU LGPL-3.0 https://www.gnu.org/licenses/lgpl-3.0.html and GNU GPL-3.0 https://www.gnu.org/licenses/gpl-3.0.html
  (to be shipped with the app as `LICENSES/LGPL-3.0.txt` and `LICENSES/GPL-3.0.txt`, to do).
- About Qt licensing: https://www.qt.io/licensing/ and https://doc.qt.io/qt-6/licensing.html.
- **Qt WebEngine** also contains Chromium and its third-party components, whose licences are listed at
  https://doc.qt.io/qt-6/qtwebengine-licensing.html (the most restrictive is the LGPL 2.1).
- **Known issue, being corrected:** the build on 2026-11-17 contained Qt modules that Qt offers only under GPL-3.0 (Qt Graphs,
  Qt Quick 3D and Quick 3D Physics, Qt Quick Timeline, Qt Virtual Keyboard). Lab Hub does not use them. They are to be removed
  from the shipped bundle, or Lab Hub is offered under the GNU AGPL-3.0 (see `LICENSE`), which permits them.

## EbookLib (GNU AGPL-3.0-or-later)

EbookLib 0.21, Copyright (C) Aleksandar Erkalovic and contributors, https://github.com/aerkalov/ebooklib, licensed under the
**GNU Affero General Public License, version 3 or later**. Lab Hub's Narrator reads and writes EPUB files with it, and it is part
of the app. Lab Hub's complete corresponding source is at https://github.com/wwds-dev/lab_hub (`git` tag for each release);
the combined application is offered under the AGPL-3.0 terms (see `LICENSE`). Text: https://www.gnu.org/licenses/agpl-3.0.html.
(`LICENSE` is the AGPL-3.0 text; the owner chose AGPL-3.0-or-later on 2026-11-17.)

## Other components

| Component | Version | Licence | Project |
|---|---|---|---|
| Pillow | 13.0.0 | MIT-CMU (HPND-style, "PIL Software License") | https://github.com/python-pillow/Pillow |
| Pillow's bundled libraries: libavif, brotli, FreeType, HarfBuzz, libjpeg-turbo, Little CMS 2, OpenJPEG, libpng, libwebp, libtiff, libxcb, zlib-ng, liblzma | as shipped in the Pillow wheel | BSD, MIT, FreeType License (FTL), zlib, public domain; see Pillow's wheel | https://pillow.readthedocs.io/en/stable/installation/third-party-licenses.html (not re-read) |
| beautifulsoup4 | 4.15.0 | MIT | https://pypi.org/project/beautifulsoup4/ |
| soupsieve | 4.0.1 | MIT | https://github.com/facelessuser/soupsieve |
| lxml | 6.1.3 | BSD-3-Clause (includes libxml2, libxslt under MIT) | https://lxml.de |
| openai (Python SDK) | 3.46.0 | Apache-2.0 | https://github.com/openai/openai-python |
| httpx2, httpcore2 | 2.16.0 | BSD-3-Clause | https://pypi.org/project/httpx2/ |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| anyio | 4.16.0 | MIT | https://github.com/agronholm/anyio |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | https://github.com/python-trio/sniffio |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| jiter | 0.19.0 | MIT | https://github.com/pydantic/jiter |
| pydantic, pydantic-core | 2.14.3, 2.50.4 | MIT | https://github.com/pydantic/pydantic |
| annotated-types, typing-inspection | 0.8.0, 0.4.5 | MIT | https://pypi.org/project/annotated-types/ |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| pypdf | 7.0.0 | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| python-dotenv | 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| tiktoken | 0.14.0 | MIT | https://github.com/openai/tiktoken |
| regex | 2026.11.8 | Apache-2.0 AND CNRI-Python (parts derived from CPython's `re`) | https://github.com/mrabarnett/mrab-regex |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3 |
| charset-normalizer | 3.5.2 | MIT | https://github.com/jawah/charset_normalizer |
| certifi | 2026.10.23 | MPL-2.0 (the `cacert.pem` CA bundle, unmodified; source https://github.com/certifi/python-certifi) | https://github.com/certifi/python-certifi |
| truststore | 0.10.5 | MIT | https://github.com/sethmlarson/truststore |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| Pygments | 2.21.0 | BSD-2-Clause | https://pygments.org |
| setuptools | 84.2.1 | MIT | https://github.com/pypa/setuptools |
| Python (CPython 3.11) and its bundled libraries | 3.11.15 | PSF-2.0 (and licences of bundled code, see https://docs.python.org/3/license.html) | https://www.python.org |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the exception that permits distributing the resulting programs under any licence | https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt |

The permissive licences above (MIT, BSD, Apache-2.0, PSF, MIT-CMU) require that their copyright notice and permission text be kept
with copies of the software: the full texts are in each project (link) and in the `*.dist-info/licenses` files of the installed
packages. Copyright lines belong to the respective authors named in those files.

## Not part of the app

Calibre (`ebook-convert`), ffmpeg, git and the Claude Code CLI are programs you install yourself; Lab Hub runs them as separate
programs and does not include them. OpenAI, ElevenLabs, Google and Anthropic are services you reach with your own accounts;
OpenAI, ElevenLabs, Google Gemini, Anthropic, Claude, Qt and macOS are trademarks of their owners and Lab Hub is not affiliated
with or endorsed by any of them.

## This list

Made 2026-11-17 from `.venv` package metadata and a listing of the installed build 175 (commit `baa2f52`). `requirements.txt`
does not pin versions, so a later build can differ: regenerate this file for every release. Not verified: individual licence
texts inside Pillow's wheel, the Chromium third-party list, the origin of `assets/tray.png`.
