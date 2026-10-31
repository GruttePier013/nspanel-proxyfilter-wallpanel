"""Render assets/icon.svg and assets/logo.svg to proxyfilter_wallpanel/icon.png and logo.png (needs playwright)."""
import pathlib
from playwright.sync_api import sync_playwright

root = pathlib.Path(__file__).resolve().parent
out = root.parent / "proxyfilter_wallpanel"
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, w, h in (("icon", 128, 128), ("logo", 250, 100)):
        page = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
        page.set_content(f"<style>html,body{{margin:0;background:transparent}}</style>{(root / (name + '.svg')).read_text()}")
        page.screenshot(path=str(out / f"{name}.png"), omit_background=True, clip={"x": 0, "y": 0, "width": w, "height": h})
    b.close()
