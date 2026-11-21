"""恢复被本工具归档的页面（PATCH archived=false）。
用法:
  python restore_page.py <页面ID...>          # 恢复指定页面
  python restore_page.py --from-archive       # 恢复本工具最近归档的页面（从记录文件读）
说明: 归档不删内容，恢复后原样回来。若内容有损，用 backup_page.py 的备份重建。
"""
import sys
import os
import json
import notion_api as api

TMP = os.environ.get("TEMP", "/tmp")
ARCHIVE_LOG = os.path.join(TMP, "notion_archived_ids.json")


def restore(ids):
    ok_n, fail_n = 0, 0
    for pid in ids:
        ok, data = api.request("PATCH", f"/pages/{pid}", {"archived": False})
        if ok and data.get("archived") is False:
            ok_n += 1
            print("  已恢复:", pid)
        else:
            fail_n += 1
            print("  失败:", pid, data.get("message", ""))
    print(f"\n完成: 成功 {ok_n}, 失败 {fail_n}")


def main():
    if "--from-archive" in sys.argv:
        if not os.path.exists(ARCHIVE_LOG):
            print("没有归档记录")
            sys.exit(1)
        with open(ARCHIVE_LOG, encoding="utf-8") as f:
            ids = json.load(f)
        restore(ids)
        return

    ids = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not ids:
        print("用法: python restore_page.py <页面ID...>  或  --from-archive")
        sys.exit(1)
    restore(ids)


if __name__ == "__main__":
    main()
