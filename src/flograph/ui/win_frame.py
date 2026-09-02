"""Windows only: make the frameless window a real snappable window again.

``Qt.FramelessWindowHint`` drops ``WS_CAPTION | WS_THICKFRAME`` from the
native window, and without those the Desktop Window Manager turns *every*
Snap feature off: edge-drag half-screen tiling, drag-to-top maximise,
Snap Assist, ``Win`` + arrow layouts and the Windows 11 Snap-Layouts
fly-out. The window just sits where you drop it.

The fix is the one Chromium, Firefox and VS Code all use — keep a normal
resizable window and only hide the frame:

* put ``WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX``
  back on the HWND (``WS_THICKFRAME`` is what DWM reads to decide a window
  is snappable; ``WS_CAPTION`` keeps the open/close/minimise animations),
* answer ``WM_NCCALCSIZE`` with the whole window rect so there is no
  visible border or title bar, and clamp it to the monitor work area
  while maximised so the taskbar stays uncovered,
* answer ``WM_NCHITTEST`` so the drag strip of our own title bar reports
  ``HTCAPTION`` (this is what makes Windows show the snap ghost) and the
  6px rim reports the resize codes.

Everything here is a no-op on macOS and Linux — those compositors snap a
``startSystemMove`` window fine, so ``window_frame.FramelessResizer``
handles them unchanged.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPoint

# -- Win32 constants -------------------------------------------------------

_GWL_STYLE = -16

_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_SYSMENU = 0x00080000

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084

_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020

_HTCLIENT = 1
_HTCAPTION = 2
_HTLEFT = 10
_HTRIGHT = 11
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17

_SW_SHOWMAXIMIZED = 3

_MONITOR_DEFAULTTONEAREST = 2

_ABM_GETSTATE = 0x0000_0004
_ABM_GETTASKBARPOS = 0x0000_0005
_ABS_AUTOHIDE = 0x0000_0001
_ABE_LEFT, _ABE_TOP, _ABE_RIGHT, _ABE_BOTTOM = 0, 1, 2, 3


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", _RECT * 3), ("lppos", ctypes.c_void_p)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("showCmd", ctypes.c_uint),
                ("ptMinPosition", wintypes.POINT),
                ("ptMaxPosition", wintypes.POINT),
                ("rcNormalPosition", _RECT)]


class _APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("hWnd", ctypes.c_void_p),
                ("uCallbackMessage", ctypes.c_ulong),
                ("uEdge", ctypes.c_ulong), ("rc", _RECT),
                ("lParam", ctypes.c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [("hWnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_ulong), ("ptX", ctypes.c_long),
                ("ptY", ctypes.c_long)]


def _loword_signed(value: int) -> int:
    v = value & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


try:  # pragma: no cover - imported for real only on Windows
    from PySide6.QtCore import QAbstractNativeEventFilter
except ImportError:  # very old PySide6
    QAbstractNativeEventFilter = object  # type: ignore


class _StyleKeeper(QObject):
    """Re-applies the native window styles after Qt might have rewritten
    them (it does on some show / window-state transitions)."""

    def __init__(self, snap: "_SnapFrame") -> None:
        super().__init__(snap._window)
        self._snap = snap

    def eventFilter(self, obj, event):  # noqa: N802 - Qt signature
        if obj is self._snap._window and event.type() in (
                QEvent.Type.Show, QEvent.Type.WinIdChange,
                QEvent.Type.WindowStateChange):
            self._snap._apply_styles()
        return False


class _SnapFrame(QAbstractNativeEventFilter):
    """The application-wide native filter. It only ever touches messages
    for our one window."""

    def __init__(self, window, title_bar, resize_margin: int) -> None:
        super().__init__()
        self._window = window
        self._title_bar = title_bar
        self._margin = max(1, resize_margin)
        self._user32 = ctypes.windll.user32
        self._shell32 = ctypes.windll.shell32
        self._get_style = getattr(self._user32, "GetWindowLongPtrW",
                                  self._user32.GetWindowLongW)
        self._set_style = getattr(self._user32, "SetWindowLongPtrW",
                                  self._user32.SetWindowLongW)
        self._get_style.restype = ctypes.c_ssize_t
        self._set_style.restype = ctypes.c_ssize_t
        self._user32.MonitorFromWindow.restype = ctypes.c_void_p
        self._keeper = _StyleKeeper(self)
        window.installEventFilter(self._keeper)

    # -- setup -----------------------------------------------------------

    def _hwnd(self):
        return int(self._window.winId())

    def _apply_styles(self) -> None:
        try:
            hwnd = self._hwnd()
        except (RuntimeError, ValueError):
            return
        style = self._get_style(hwnd, _GWL_STYLE)
        want = (style | _WS_CAPTION | _WS_THICKFRAME | _WS_MAXIMIZEBOX
                | _WS_MINIMIZEBOX | _WS_SYSMENU)
        if want != style:
            self._set_style(hwnd, _GWL_STYLE, want)
            self._user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER
                | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)

    # -- state helpers -------------------------------------------------

    def _is_maximized(self) -> bool:
        placement = _WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(_WINDOWPLACEMENT)
        if self._user32.GetWindowPlacement(self._hwnd(),
                                           ctypes.byref(placement)):
            return placement.showCmd == _SW_SHOWMAXIMIZED
        return False

    def _autohide_edge(self):
        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(_APPBARDATA)
        state = self._shell32.SHAppBarMessage(_ABM_GETSTATE,
                                              ctypes.byref(data))
        if not (state & _ABS_AUTOHIDE):
            return None
        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(_APPBARDATA)
        if self._shell32.SHAppBarMessage(_ABM_GETTASKBARPOS,
                                         ctypes.byref(data)):
            return data.uEdge
        return _ABE_BOTTOM

    # -- message handlers --------------------------------------------

    def _on_nccalcsize(self, lparam: int) -> None:
        """Client area == whole window (no frame). While maximised, pin it
        to the monitor work area so the taskbar is not covered."""
        if not self._is_maximized():
            return
        monitor = self._user32.MonitorFromWindow(self._hwnd(),
                                                 _MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not self._user32.GetMonitorInfoW(ctypes.c_void_p(monitor),
                                            ctypes.byref(info)):
            return
        params = _NCCALCSIZE_PARAMS.from_address(lparam)
        rc = params.rgrc[0]
        rc.left, rc.top = info.rcWork.left, info.rcWork.top
        rc.right, rc.bottom = info.rcWork.right, info.rcWork.bottom
        edge = self._autohide_edge()
        if edge == _ABE_TOP:
            rc.top += 1
        elif edge == _ABE_LEFT:
            rc.left += 1
        elif edge == _ABE_RIGHT:
            rc.right -= 1
        elif edge is not None:
            rc.bottom -= 1

    def _on_nchittest(self, lparam: int):
        x, y = _loword_signed(lparam), _loword_signed(lparam >> 16)
        win = self._window
        local = win.mapFromGlobal(QPoint(x, y))
        w, h = win.width(), win.height()
        if not (0 <= local.x() < w and 0 <= local.y() < h):
            return None
        m = self._margin
        if self._is_maximized():
            on_left = on_right = on_top = on_bottom = False
        else:
            on_left = local.x() < m
            on_right = local.x() >= w - m
            on_top = local.y() < m
            on_bottom = local.y() >= h - m
        if on_top and on_left:
            return _HTTOPLEFT
        if on_top and on_right:
            return _HTTOPRIGHT
        if on_bottom and on_left:
            return _HTBOTTOMLEFT
        if on_bottom and on_right:
            return _HTBOTTOMRIGHT
        if on_left:
            return _HTLEFT
        if on_right:
            return _HTRIGHT
        if on_top:
            return _HTTOP
        if on_bottom:
            return _HTBOTTOM
        bar = self._title_bar
        bar_pt = bar.mapFromGlobal(QPoint(x, y))
        if bar.rect().contains(bar_pt) and bar.childAt(bar_pt) is None:
            return _HTCAPTION
        return _HTCLIENT

    # -- the filter -------------------------------------------------

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = _MSG.from_address(int(message))
            if not self._window.isVisible() or msg.hWnd != self._hwnd():
                return False, 0
            if msg.message == _WM_NCCALCSIZE:
                if msg.wParam:
                    self._on_nccalcsize(msg.lParam)
                    return True, 0
                return False, 0
            if msg.message == _WM_NCHITTEST:
                hit = self._on_nchittest(msg.lParam)
                if hit is not None:
                    return True, hit
        except Exception:  # never let a filter bug kill the event loop
            return False, 0
        return False, 0


def enable_windows_snap(window, title_bar, resize_margin: int = 6):
    """Give *window* (a frameless top-level) native Windows Snap back.

    Returns the installed filter (which the caller must keep a reference
    to) or ``None`` on any non-Windows platform or if setup fails.
    """
    if sys.platform != "win32":
        return None
    try:
        from PySide6.QtWidgets import QApplication

        frame = _SnapFrame(window, title_bar, resize_margin)
        QApplication.instance().installNativeEventFilter(frame)
        frame._apply_styles()
        return frame
    except Exception:
        return None
