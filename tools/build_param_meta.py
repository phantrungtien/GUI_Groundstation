"""Dung core/param_meta.json — mo ta MOI tham so ArduCopter cho tab Trang thai.

Nguon: file apm.pdef.xml ma Mission Planner tai ve (ban master, dung ten SI cua
4.7-dev: RTL_ALT_M, WP_SPD...). Ma nguon ~/ardupilot tren may la 4.6.3, sinh ra
ten cu — khong khop FC. Doi firmware thi mo Mission Planner mot lan (no tu tai
lai file) roi chay:

    python3 tools/build_param_meta.py [duong/dan/ArduCopter.apm.pdef.xml]

Chi giu nhung gi cot giai thich can: ten de doc, mo ta, don vi, cac gia tri.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path.home() / ".local/share/Mission Planner/ArduCopter.apm.pdef.xml"
OUT = Path(__file__).resolve().parent.parent / "core" / "param_meta.json"


def build(src):
    out = {}
    for p in ET.parse(src).getroot().iter("param"):
        name = p.get("name", "").split(":")[-1]  # "ArduCopter:RTL_ALT_M" -> "RTL_ALT_M"
        if not name or name in out:
            continue  # trung ten: giu ban dau tien (phan vehicle dung truoc libraries)
        f = {x.get("name"): (x.text or "").strip() for x in p.findall("field")}
        vals = ", ".join(f"{v.get('code')}: {(v.text or '').strip()}"
                         for v in p.iter("value"))
        out[name] = [p.get("humanName", ""), " ".join(p.get("documentation", "").split()),
                     f.get("Units", ""), vals]
    return out


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    meta = build(src)
    OUT.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    print(f"{len(meta)} tham so -> {OUT} ({OUT.stat().st_size // 1024} KB)")
