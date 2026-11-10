"""把 runs_dual/*.json 的 4 张图各导出一张独立 PNG（2 倍像素）。

    python export_png.py            # 导出全部
    python export_png.py --scale 3  # 更高清

依赖本机 Chrome 的 headless 截图，不联网、不调模型。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from render_dual import svg_exec, svg_privacy

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).parent / "runs_dual"
IMG = OUT / "img"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
SCALE = 2
W = 1100

TASKS = [("banking", "user_task_1"), ("banking", "user_task_4")]


def _shot(svg: str, dest: Path):
    """按 svg 的 viewBox 高度定窗口，保证 1:1 不裁切。"""
    m = re.search(r'viewBox="0 0 (\d+) ([\d.]+)"', svg)
    h = float(m.group(2))
    html = ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            f"body{{margin:0;background:#fff}}div{{width:{W}px}}</style></head>"
            f"<body><div>{svg}</div></body></html>")
    tmp = Path(tempfile.gettempdir()) / "_export_tmp.html"
    tmp.write_text(html, encoding="utf-8")
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--default-background-color=FFFFFFFF",
                    f"--force-device-scale-factor={SCALE}",
                    f"--window-size={W},{int(h) + 2}",
                    f"--screenshot={dest}", tmp.as_uri()],
                   check=True, capture_output=True, timeout=90)


def main():
    IMG.mkdir(parents=True, exist_ok=True)
    for suite, tid in TASKS:
        stem = f"{suite}_{tid}"
        run = json.loads((OUT / f"{stem}.exec.json").read_text(encoding="utf-8"))
        pg = json.loads((OUT / f"{stem}.privacy.json").read_text(encoding="utf-8"))
        for kind, svg in (("exec", svg_exec(run)), ("privacy", svg_privacy(pg))):
            dest = IMG / f"{stem}_{kind}.png"
            _shot(svg, dest)
            print(f"  {dest.name}  {dest.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
