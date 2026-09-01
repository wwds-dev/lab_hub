"""Showing and hiding the Dock icon.

Lab Hub is two things at once: a window you open occasionally, and a menu bar
item that stays. macOS has a matching pair of activation policies, and the app
switches between them so the Dock only carries an icon when there is actually a
window behind it:

* ``Regular`` — Dock icon, ⌘-Tab entry, a menu bar of its own;
* ``Accessory`` — none of those, status item only.

Reached through the Objective-C runtime with ctypes rather than pyobjc. This is
the only AppKit call the app needs, and pulling a whole framework binding into
the bundle for one selector is not worth the weight — PyInstaller already has
enough to get wrong.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

# NSApplicationActivationPolicy
REGULAR = 0
ACCESSORY = 1

_VOID = ctypes.c_void_p


def _runtime():
    """The Objective-C runtime, with the signatures we use declared.

    objc_msgSend is variadic in C; ctypes needs the exact argument types for
    each call or it pushes them in the wrong registers on arm64 and the call
    silently misbehaves.
    """
    # find_library shells out and inspects the linker environment, which
    # PyInstaller rewrites — inside the bundle it comes back empty and the Dock
    # icon silently never hides. The absolute path always resolves: since macOS
    # 11 libobjc is served from the dyld shared cache rather than a real file,
    # and dlopen finds it there.
    candidates = [ctypes.util.find_library("objc"), "/usr/lib/libobjc.A.dylib"]
    objc = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            objc = ctypes.cdll.LoadLibrary(candidate)
            break
        except OSError:
            continue
    if objc is None:
        return None

    objc.objc_getClass.restype = _VOID
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = _VOID
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return objc


def available() -> bool:
    return sys.platform == "darwin" and _runtime() is not None


def set_policy(policy: int) -> bool:
    """Apply an activation policy. False if the call could not be made."""
    if sys.platform != "darwin":
        return False
    objc = _runtime()
    if objc is None:
        return False

    shared = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(_VOID, _VOID, _VOID))
    app = shared(
        objc.objc_getClass(b"NSApplication"),
        objc.sel_registerName(b"sharedApplication"),
    )
    if not app:
        return False

    apply_policy = ctypes.cast(
        objc.objc_msgSend, ctypes.CFUNCTYPE(ctypes.c_bool, _VOID, _VOID, ctypes.c_long)
    )
    return bool(
        apply_policy(app, objc.sel_registerName(b"setActivationPolicy:"), policy)
    )


def show_in_dock() -> bool:
    return set_policy(REGULAR)


def hide_from_dock() -> bool:
    return set_policy(ACCESSORY)
