#!/usr/bin/env python3
"""对比源 skill 库与目标文件夹，输出差异；默认只复制目标缺失的 skill，保护目标增强版。

用法:
  python sync_skills.py --source <源目录> --target <目标目录> [--dry-run] [--force]
"""
import argparse
import filecmp
import shutil
import sys
from pathlib import Path


def skill_dirs(root: Path):
    """根目录下的一级子目录视为 skill（忽略隐藏目录）。"""
    return {p.name: p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}


def dir_diff(src: Path, dst: Path):
    """返回 (仅源有, 仅目标有, 内容不同) 的相对路径列表。"""
    cmp = filecmp.dircmp(str(src), str(dst))
    src_only, dst_only, differ = [], [], []

    def walk(c, prefix=""):
        for n in c.left_only:
            src_only.append(prefix + n)
        for n in c.right_only:
            dst_only.append(prefix + n)
        for n in c.diff_files:
            differ.append(prefix + n)
        for sub in c.subdirs.values():
            sub_name = Path(sub.left).name
            walk(sub, prefix + sub_name + "/")

    walk(cmp)
    return sorted(src_only), sorted(dst_only), sorted(differ)


def main():
    ap = argparse.ArgumentParser(description="对比并同步 skill 库")
    ap.add_argument("--source", required=True, help="源 skill 库目录")
    ap.add_argument("--target", required=True, help="目标文件夹")
    ap.add_argument("--dry-run", action="store_true", help="只报告差异，不改动文件")
    ap.add_argument("--force", action="store_true", help="用源覆盖目标已有的同名 skill")
    args = ap.parse_args()

    src_root, dst_root = Path(args.source), Path(args.target)
    if not src_root.is_dir():
        sys.exit(f"源目录不存在: {src_root}")
    if not dst_root.is_dir():
        sys.exit(f"目标目录不存在: {dst_root}")

    src = skill_dirs(src_root)
    dst = skill_dirs(dst_root)

    missing = [n for n in src if n not in dst]      # 目标没有 -> 可复制
    extra = [n for n in dst if n not in src]        # 目标独有 -> 保留
    changed = []                                    # 同名但内容不同
    for name in sorted(src.keys() & dst.keys()):
        so, do, df = dir_diff(src[name], dst[name])
        if so or do or df:
            changed.append((name, so, do, df))

    print(f"源 skill: {len(src)} 个 | 目标 skill: {len(dst)} 个")
    print(f"\n目标缺失（将复制）: {missing or '无'}")
    print(f"目标独有（保留）: {extra or '无'}")
    print("\n同名但内容不同:")
    if not changed:
        print("  无")
    for name, so, do, df in changed:
        print(f"  [{name}]")
        print(f"    仅源有: {so or '无'}")
        print(f"    仅目标有: {do or '无'}")
        print(f"    内容不同: {df or '无'}")

    if args.dry_run:
        print("\n(dry-run，未改动任何文件)")
        return

    copied = []
    for name in missing:
        shutil.copytree(src[name], dst[name])
        copied.append(name)

    if args.force:
        for name, *_ in changed:
            shutil.rmtree(dst[name])
            shutil.copytree(src[name], dst[name])
            copied.append(name + "(覆盖)")

    print(f"\n已复制: {copied or '无'}")


if __name__ == "__main__":
    main()
