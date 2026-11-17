"""scripts/prune_gpl_qt.sh removes exactly the unused GPL-only Qt modules.

Runs the script under /bin/bash (macOS ships bash 3.2) against a fake bundle
laid out like PyInstaller's: real files under Frameworks/PySide6/Qt and
symlinks to them from Frameworks/ and Resources/.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prune_gpl_qt.sh"
QT = "Frameworks/PySide6/Qt"

MUST_GO = [
    f"{QT}/lib/QtGraphs.framework/Versions/A/QtGraphs",
    f"{QT}/lib/QtGraphs2DImpl.framework/Versions/A/QtGraphs2DImpl",
    f"{QT}/lib/QtGraphsWidgets.framework/Versions/A/QtGraphsWidgets",
    f"{QT}/lib/QtQuick3D.framework/Versions/A/QtQuick3D",
    f"{QT}/lib/QtQuick3DPhysics.framework/Versions/A/QtQuick3DPhysics",
    f"{QT}/lib/QtQuick3DPhysicsHelpers.framework/Versions/A/QtQuick3DPhysicsHelpers",
    f"{QT}/lib/QtQuickTimeline.framework/Versions/A/QtQuickTimeline",
    f"{QT}/lib/QtQuickTimelineBlendTrees.framework/Versions/A/QtQuickTimelineBlendTrees",
    f"{QT}/lib/QtVirtualKeyboard.framework/Versions/A/QtVirtualKeyboard",
    f"{QT}/lib/QtVirtualKeyboardSettings.framework/Versions/A/QtVirtualKeyboardSettings",
    f"{QT}/lib/QtCharts.framework/Versions/A/QtCharts",
    f"{QT}/lib/QtDataVisualizationQml.framework/Versions/A/QtDataVisualizationQml",
    f"{QT}/qml/QtGraphs/libgraphsplugin.dylib",
    f"{QT}/qml/QtQuick3D/Physics/libqquick3dphysicsplugin.dylib",
    f"{QT}/qml/QtQuick/Timeline/libqtquicktimelineplugin.dylib",
    f"{QT}/qml/QtQuick/VirtualKeyboard/Core/libvirtualkeyboardplugin.dylib",
    f"{QT}/qml/QtCharts/libqtchartsqml2plugin.dylib",
    f"{QT}/qml/QtDataVisualization/libdatavisualizationqmlplugin.dylib",
    f"{QT}/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.dylib",
    f"{QT}/plugins/qmltooling/libqmldbg_quick3dprofiler.dylib",
    "Frameworks/PySide6/QtGraphs.abi3.so",
    "Frameworks/PySide6/QtQuick3D.pyi",
]

MUST_STAY = [
    f"{QT}/lib/QtQuick.framework/Versions/A/QtQuick",
    f"{QT}/lib/QtQuickWidgets.framework/Versions/A/QtQuickWidgets",
    f"{QT}/lib/QtQml.framework/Versions/A/QtQml",
    f"{QT}/lib/Qt3DCore.framework/Versions/A/Qt3DCore",
    f"{QT}/lib/Qt3DQuickScene3D.framework/Versions/A/Qt3DQuickScene3D",
    f"{QT}/lib/QtWebEngineCore.framework/Versions/A/QtWebEngineCore",
    f"{QT}/lib/QtWebEngineWidgets.framework/Versions/A/QtWebEngineWidgets",
    f"{QT}/qml/Qt3D/Core/libquick3dcoreplugin.dylib",
    f"{QT}/qml/QtQuick/Controls/libqtquickcontrols2plugin.dylib",
    f"{QT}/plugins/platforms/libqcocoa.dylib",
    "Frameworks/PySide6/QtWebEngineCore.abi3.so",
    "Resources/LICENSE",
    "Resources/LICENSES/GPL-3.0.txt",
]


def framework_name(rel: str) -> str | None:
    part = rel.split("/")[4] if rel.startswith(f"{QT}/lib/") else None
    return part.removesuffix(".framework") if part else None


def make_bundle(root: Path) -> Path:
    contents = root / "Lab Hub.app" / "Contents"
    for rel in MUST_GO + MUST_STAY:
        path = contents / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        name = framework_name(rel)
        if name:  # PyInstaller's links from Frameworks/ and Resources/
            for top in ("Frameworks", "Resources"):
                link = contents / top / name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(os.path.relpath(path, link.parent))
    return root / "Lab Hub.app"


def run(app: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), str(app)],
        capture_output=True,
        text=True,
        env={**os.environ, "PRUNE_SKIP_OTOOL": "1"},
    )


def test_removes_exactly_the_gpl_only_modules(tmp_path):
    app = make_bundle(tmp_path)

    result = run(app)

    assert result.returncode == 0, result.stderr
    contents = app / "Contents"
    assert [rel for rel in MUST_GO if (contents / rel).exists()] == []
    assert [rel for rel in MUST_STAY if not (contents / rel).exists()] == []
    for rel in MUST_STAY:
        name = framework_name(rel)
        if name:
            assert (contents / "Resources" / name).resolve().exists(), name
    dangling = [p for p in contents.rglob("*") if p.is_symlink() and not p.exists()]
    assert dangling == []


@pytest.mark.parametrize(
    "renamed",
    [
        f"{QT}/qml/QtQuick3DNext/libqquick3dnextplugin.dylib",  # a moved QML module
        f"{QT}/plugins/graphs/libgraphsbackend.dylib",  # a new plugin folder
    ],
)
def test_fails_when_a_module_is_renamed_past_the_patterns(tmp_path, renamed):
    app = make_bundle(tmp_path)
    path = app / "Contents" / renamed
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")

    result = run(app)

    assert result.returncode != 0
    assert "still in the bundle" in result.stderr


def test_fails_on_an_unrelated_dangling_link(tmp_path):
    app = make_bundle(tmp_path)
    (app / "Contents" / "Resources" / "stale").symlink_to("nowhere")

    result = run(app)

    assert result.returncode != 0
    assert "dangling symlinks" in result.stderr


def test_refuses_a_path_that_is_not_a_bundle(tmp_path):
    result = run(tmp_path / "missing.app")

    assert result.returncode != 0
    assert "not an app bundle" in result.stderr
