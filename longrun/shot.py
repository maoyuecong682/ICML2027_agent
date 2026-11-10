"""把 SVG 渲染成 PNG：用本机 Chrome headless 按 viewBox 高度定窗口，避免裁切。

不联网、不调模型，纯本地截图。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def shot(svg: str, dest: Path, scale: int = 2) -> Path:
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if not m:
        raise ValueError("svg 缺少 viewBox")
    w, h = float(m.group(1)), float(m.group(2))
    html = ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            f"body{{margin:0;background:#fff}}div{{width:{w:.0f}px}}</style></head>"
            f"<body><div>{svg}</div></body></html>")
    tmp = Path(tempfile.gettempdir()) / "_shot_tmp.html"
    tmp.write_text(html, encoding="utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--default-background-color=FFFFFFFF",
         f"--force-device-scale-factor={scale}",
         f"--window-size={w:.0f},{h + 2:.0f}",
         f"--screenshot={dest}", tmp.as_uri()],
        check=True, capture_output=True, timeout=120)
    return dest
