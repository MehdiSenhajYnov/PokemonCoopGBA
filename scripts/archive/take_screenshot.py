"""Take a screenshot of the mGBA window and save it.
Usage: python scripts/ToUse/take_screenshot.py [output_name]
"""
import sys
import time
from PIL import ImageGrab
import ctypes

def find_mgba_window():
    """Find the mGBA window and return its rect."""
    import ctypes.wintypes

    windows = []

    def callback(hwnd, param):
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            title = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, title, length + 1)
            if 'mGBA' in title.value or 'RunBun' in title.value or 'Pokemon' in title.value:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if rect.right - rect.left > 50:  # Ignore tiny windows
                    windows.append((title.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)

    return windows

def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "mgba_screenshot"
    output_path = f"C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\{output}.png"

    windows = find_mgba_window()
    if windows:
        title, rect = windows[0]
        print(f"Found window: '{title}' at {rect}")
        # Add small padding to exclude window borders
        img = ImageGrab.grab(bbox=rect)
        img.save(output_path)
        print(f"Screenshot saved to {output_path}")
    else:
        print("mGBA window not found, taking full screen")
        img = ImageGrab.grab()
        img.save(output_path)
        print(f"Full screenshot saved to {output_path}")

if __name__ == "__main__":
    main()
