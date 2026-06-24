#!/usr/bin/env python3
"""
CI/离线结构校验工具 —— b 方案的结构半场。

用 jsonschema 校验 output/global/*.json 是否符合 model/schema/*.schema.json。
**仅供 CI 与离线开发使用,不在运行时后端调用**(后端运行时只跑纯标准库的
pipeline/validate.py 的 R1–R6 语义规则)。

依赖:jsonschema(开发依赖,非后端运行时依赖)。
用法:python tools/schema_check.py --global-dir output/global --schema-dir model/schema
"""
import os, json, glob, sys, argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--global-dir", required=True)
    ap.add_argument("--schema-dir", required=True)
    args = ap.parse_args()

    try:
        from jsonschema import Draft202012Validator, RefResolver
    except ImportError:
        print("需要 jsonschema:pip install jsonschema(开发依赖)", file=sys.stderr)
        sys.exit(2)

    store = {}
    for f in glob.glob(os.path.join(args.schema_dir, "*.schema.json")):
        s = json.load(open(f, encoding="utf-8"))
        store[s["$id"]] = s
        store[os.path.basename(f)] = s

    pairs = [
        ("global_characters.schema.json", "characters.json"),
        ("global_items.schema.json", "items.json"),
        ("global_locations.schema.json", "locations.json"),
        ("global_timeline.schema.json", "timeline.json"),
        ("global_scenes.schema.json", "scenes.json"),
    ]
    failed = False
    for sch_name, data_name in pairs:
        sch_path = os.path.join(args.schema_dir, sch_name)
        data_path = os.path.join(args.global_dir, data_name)
        if not os.path.isfile(sch_path) or not os.path.isfile(data_path):
            print(f"skip {data_name} (缺文件)")
            continue
        s = json.load(open(sch_path, encoding="utf-8"))
        resolver = RefResolver(base_uri=f"file://{os.path.abspath(sch_path)}",
                               referrer=s, store=store)
        v = Draft202012Validator(s, resolver=resolver)
        errs = sorted(v.iter_errors(json.load(open(data_path, encoding="utf-8"))),
                      key=lambda e: list(e.path))
        if errs:
            failed = True
            print(f"✗ {data_name} ({len(errs)} errors)")
            for e in errs[:8]:
                print("   ", list(e.path), "→", e.message[:100])
        else:
            print(f"✓ {data_name} PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
