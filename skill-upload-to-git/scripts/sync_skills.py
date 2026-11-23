#!/usr/bin/env python3
"""对比源 skill 库与目标文件夹，输出差异；同名 skill 默认用源逐文件覆盖目标。
同时可把 MCP 服务端代码同步到目标仓库的 .mcp-servers/ 下。

用法:
  python sync_skills.py --source <源目录> --target <目标目录> [--dry-run] [--keep-target]
                        [--mcp-source <MCP源目录>] [--mcp-target <MCP目标目录>] [--no-mcp]

新流程（git 目标库为真相源，反向分发到 CC Switch）示例:
  python sync_skills.py \
    --source "D:/My_Program/Ai Work_Space/My Skills" \
    --target "C:/Users/123456/.cc-switch/skills" \
    --mcp-source "D:/My_Program/Ai Work_Space/My Skills/.mcp-servers" \
    --mcp-target "C:/Users/123456/.mcp-servers"

默认规则（在目标基础上用新版改写）:
  - 目标缺失的目录：从源整体复制
  - 目标独有的目录：保留（源没有，无从覆盖）
  - 同名但内容不同：把源的文件逐个覆盖到目标同名文件；
    目标里独有的文件/目录全部保留，不删除。
  - 加 --keep-target 可恢复旧行为：同名时保留目标版本，不覆盖。

MCP 同步（默认开启）:
  - 源默认 C:/Users/123456/.mcp-servers，目标默认 <target>/.mcp-servers
  - --mcp-source 覆盖源路径；--mcp-target 覆盖目标路径；--no-mcp 关闭 MCP 同步
  - 用点开头的 .mcp-servers 作目录名，避免被当成 skill 同步
  - 忽略 __pycache__ 与 *.pyc
"""
import argparse
import filecmp
import shutil
import sys
from pathlib import Path

DEFAULT_MCP_SOURCE = "C:/Users/123456/.mcp-servers"
MCP_DIRNAME = ".mcp-servers"
IGNORE_NAMES = ["__pycache__", "*.pyc", ".DS_Store", "Thumbs.db"]


def _ignored(name: str) -> bool:
    return name == "__pycache__" or name.endswith(".pyc") or name in (".DS_Store", "Thumbs.db")


def skill_dirs(root: Path):
    """根目录下的一级子目录视为一个单元（忽略隐藏目录）。"""
    return {p.name: p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}


def dir_diff(src: Path, dst: Path):
    """返回 (仅源有, 仅目标有, 内容不同) 的相对路径列表。"""
    cmp = filecmp.dircmp(str(src), str(dst), ignore=IGNORE_NAMES)
    src_only, dst_only, differ = [], [], []

    def walk(c, prefix=""):
        for n in c.left_only:
            if not _ignored(n):
                src_only.append(prefix + n)
        for n in c.right_only:
            if not _ignored(n):
                dst_only.append(prefix + n)
        for n in c.diff_files:
            if not _ignored(n):
                differ.append(prefix + n)
        for sub in c.subdirs.values():
            sub_name = Path(sub.left).name
            walk(sub, prefix + sub_name + "/")

    walk(cmp)
    return sorted(src_only), sorted(dst_only), sorted(differ)


def overlay(src: Path, dst: Path):
    """把 src 的文件逐个覆盖到 dst 的同名文件，dst 独有的文件/目录保留。"""
    for item in src.iterdir():
        if _ignored(item.name):
            continue
        target = dst / item.name
        if item.is_dir():
            if target.is_dir():
                overlay(item, target)
            else:
                shutil.copytree(item, target, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
        else:
            shutil.copy2(item, target)


def sync_group(label: str, src_root: Path, dst_root: Path, args):
    """同步一组目录（skill 或 MCP）：对比、报告、按规则复制覆盖。"""
    if not src_root.is_dir():
        print(f"\n=== [{label}] 源目录不存在，跳过: {src_root} ===")
        return
    dst_root.mkdir(parents=True, exist_ok=True)

    src = skill_dirs(src_root)
    dst = skill_dirs(dst_root)
    missing = [n for n in src if n not in dst]
    extra = [n for n in dst if n not in src]
    changed = []
    for name in sorted(src.keys() & dst.keys()):
        so, do, df = dir_diff(src[name], dst[name])
        if so or do or df:
            changed.append((name, so, do, df))

    print(f"\n=== [{label}] 源 {len(src)} 个 | 目标 {len(dst)} 个 ===")
    print(f"目标缺失（将复制）: {missing or '无'}")
    print(f"目标独有（保留）: {extra or '无'}")
    print("同名但内容不同:")
    if not changed:
        print("  无")
    for name, so, do, df in changed:
        print(f"  [{name}]")
        print(f"    仅源有（将复制）: {so or '无'}")
        print(f"    仅目标有（将保留）: {do or '无'}")
        print(f"    内容不同（源覆盖目标）: {df or '无'}")
    if changed and args.keep_target:
        print("\n  (--keep-target：以上同名单元将保留目标版本，不覆盖)")

    if args.dry_run:
        return

    applied = []
    for name in missing:
        shutil.copytree(src[name], dst[name], ignore=shutil.ignore_patterns(*IGNORE_NAMES))
        applied.append(name + "(复制)")
    if not args.keep_target:
        for name, *_ in changed:
            overlay(src[name], dst[name])
            applied.append(name + "(覆盖同名文件，保留目标独有)")

    print(f"  已应用: {applied or '无'}")
    if extra:
        print(f"  目标独有（保留未动）: {extra}")


def main():
    ap = argparse.ArgumentParser(description="对比并同步 skill 库与 MCP 服务端代码")
    ap.add_argument("--source", required=True, help="源 skill 库目录")
    ap.add_argument("--target", required=True, help="目标文件夹")
    ap.add_argument("--dry-run", action="store_true", help="只报告差异，不改动文件")
    ap.add_argument("--keep-target", action="store_true",
                    help="同名内容不同时保留目标版本（默认用源逐文件覆盖）")
    ap.add_argument("--mcp-source", default=DEFAULT_MCP_SOURCE,
                    help=f"MCP 服务端源目录（默认 {DEFAULT_MCP_SOURCE}）")
    ap.add_argument("--mcp-target", default=None,
                    help="MCP 服务端目标目录（默认 <target>/.mcp-servers；反向分发时传本地运行位置）")
    ap.add_argument("--no-mcp", action="store_true", help="关闭 MCP 同步（默认开启）")
    args = ap.parse_args()

    src_root, dst_root = Path(args.source), Path(args.target)
    if not src_root.is_dir():
        sys.exit(f"源目录不存在: {src_root}")
    if not dst_root.is_dir():
        sys.exit(f"目标目录不存在: {dst_root}")

    print(f"skill: {src_root}  ->  {dst_root}")
    sync_group("skill", src_root, dst_root, args)

    if not args.no_mcp:
        mcp_src = Path(args.mcp_source)
        mcp_dst = Path(args.mcp_target) if args.mcp_target else dst_root / MCP_DIRNAME
        print(f"\nmcp:   {mcp_src}  ->  {mcp_dst}")
        sync_group("mcp", mcp_src, mcp_dst, args)

    if args.dry_run:
        print("\n(dry-run，未改动任何文件)")


if __name__ == "__main__":
    main()
