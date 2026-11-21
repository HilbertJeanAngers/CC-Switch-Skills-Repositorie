"""分析 Notion 页面结构：列出所有图片及其前置文字，标出缺注释的裸图。
用法: python analyze_page.py <页面标题关键词或页面ID>
"""
import sys
import json
import os
import notion_api as api


def is_heading(block):
    return block.get("type", "").startswith("heading")


def is_label(block):
    """能作为图片说明的块类型：段落/标题/callout/项目符号。"""
    return block.get("type") in ("paragraph", "callout", "heading_1", "heading_2", "heading_3",
                                 "bulleted_list_item", "numbered_list_item", "toggle")


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else None
    if not kw:
        print("用法: python analyze_page.py <页面标题关键词或页面ID>")
        sys.exit(1)

    # 判断是 ID 还是关键词
    page = None
    if "-" in kw and len(kw) > 30:
        ok, data = api.request("GET", f"/pages/{kw}")
        if ok:
            page = data
    if page is None:
        matches = api.find_page(kw)
        if not matches:
            print(f"未找到标题含 '{kw}' 的页面")
            sys.exit(1)
        if len(matches) > 1:
            print("找到多个页面，请用完整标题或页面ID：")
            for m in matches:
                print(f"  {m['id']}  {m['title']}  {m['edited'][:10]}")
            sys.exit(2)
        page = api.request("GET", f"/pages/{matches[0]['id']}")[1]
        kw = matches[0]["id"]

    print(f"页面: {page.get('id')}")
    print("=" * 70)

    top = api.children(page["id"])
    report = []
    img_no = 0
    section = ""
    pending_label = ""  # 最近一段文字，作为后续图片的候选说明

    for b in top:
        t = api.rich_text(b)
        if is_heading(b):
            section = t
            print(f"\n## {t}")
            pending_label = ""
        elif is_label(b) and t.strip() and not b.get("has_children"):
            pending_label = t.strip()
            print(f"  [文字] {t.strip()[:60]}")
        elif b.get("type") == "child_page":
            print(f"  [子页] {t}")

        # 无论 heading 还是普通块，只要有子块就进去找图片
        if b.get("has_children"):
            subs = api.children(b["id"])
            if t.strip() and not is_heading(b):
                pending_label = t.strip()
                print(f"  [文字·含子块] {t.strip()[:60]}")
            for s in subs:
                st = api.rich_text(s)
                if is_label(s) and st.strip():
                    pending_label = st.strip()
                    print(f"    [文字] {st.strip()[:60]}")
                if s.get("type") == "image":
                    img_no += 1
                    bare = not pending_label.strip()
                    flag = "  <<< 裸图·缺注释" if bare else ""
                    print(f"    [图 #{img_no}] 说明='{pending_label[:30]}' id={s['id']}{flag}")
                    report.append({
                        "n": img_no, "block_id": s["id"], "section": section,
                        "label": pending_label, "bare": bare,
                        "url": api.image_url(s),
                    })

    bare_count = sum(1 for r in report if r["bare"])
    print("\n" + "=" * 70)
    print(f"图片总数: {len(report)}  裸图(缺注释): {bare_count}")

    out = os.path.join(os.environ.get("TEMP", "/tmp"), "notion_page_analysis.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"page_id": page["id"], "images": report}, f, ensure_ascii=False, indent=2)
    print(f"详细数据: {out}")


if __name__ == "__main__":
    main()
