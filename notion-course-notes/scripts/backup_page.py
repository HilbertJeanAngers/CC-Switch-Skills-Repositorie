"""备份 Notion 页面完整内容（用于改前留底 / 恢复）。
用法: python backup_page.py <页面ID> [输出路径]
默认输出到当前工作目录 notion_backup_<页面ID前8位>_<日期>.json
"""
import sys
import os
import json
import datetime
import notion_api as api


def snapshot(page_id):
    ok, page = api.request("GET", f"/pages/{page_id}")
    if not ok:
        raise RuntimeError(f"读取页面失败: {page}")
    result = {"page_id": page_id, "page": page, "blocks": {}}

    def walk(block_id):
        blocks = api.children(block_id)
        result["blocks"][block_id] = blocks
        for b in blocks:
            if b.get("has_children"):
                walk(b["id"])

    walk(page_id)
    return result


def main():
    if len(sys.argv) < 2:
        print("用法: python backup_page.py <页面ID> [输出路径]")
        sys.exit(1)
    page_id = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"notion_backup_{page_id[:8]}_{datetime.date.today()}.json"
    data = snapshot(page_id)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    n = sum(len(v) for v in data["blocks"].values())
    print(f"✅ 备份完成: {out} ({n} 个块)")


if __name__ == "__main__":
    main()
