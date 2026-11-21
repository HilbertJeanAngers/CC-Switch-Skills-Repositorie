"""在指定图片前插入注释文字。风格由 references/STYLE.md 控制。
用法:
  python insert_caption.py <页面ID> <图片编号> <注释文字>
  python insert_caption.py --config          # 查看当前风格配置
说明:
  图片编号来自 analyze_page.py 的输出。脚本会自动定位该图的父块和前一个块，
  把注释插在它前面。after 参数放在 body 里（Notion API 要求）。
"""
import sys
import os
import json
import notion_api as api

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLE_FILE = os.path.join(SKILL_DIR, "references", "STYLE.md")
TMP = os.environ.get("TEMP", "/tmp")
ANALYSIS = os.path.join(TMP, "notion_page_analysis.json")


def load_style():
    """从 STYLE.md 解析 block_type 和 prefix/suffix 配置。
    STYLE.md 里用注释行标注：
      <!-- block_type: paragraph -->
      <!-- prefix: "" -->
      <!-- suffix: "" -->
    """
    cfg = {"block_type": "paragraph", "prefix": "", "suffix": ""}
    if os.path.exists(STYLE_FILE):
        with open(STYLE_FILE, encoding="utf-8") as f:
            text = f.read()
        for key in ("block_type", "prefix", "suffix"):
            marker = f"{key}:"
            for line in text.splitlines():
                if marker in line and "<!--" in line:
                    val = line.split(marker, 1)[1].split("-->")[0].strip().strip('"').strip("'")
                    cfg[key] = val
                    break
    return cfg


def make_block(text, block_type):
    if block_type == "heading_3":
        return api.heading3_block(text)
    if block_type == "heading_2":
        return {
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
        }
    if block_type == "callout":
        return {
            "object": "block", "type": "callout",
            "callout": {"rich_text": [{"type": "text", "text": {"content": text}}], "icon": {"type": "emoji", "emoji": "📌"}},
        }
    return api.paragraph_block(text)


def main():
    if "--config" in sys.argv:
        print("当前风格配置:", json.dumps(load_style(), ensure_ascii=False))
        print("配置文件:", STYLE_FILE)
        return

    if len(sys.argv) < 4:
        print("用法: python insert_caption.py <页面ID> <图片编号> <注释文字>")
        sys.exit(1)

    page_id, num, caption = sys.argv[1], int(sys.argv[2]), " ".join(sys.argv[3:])
    cfg = load_style()
    final_text = f"{cfg['prefix']}{caption}{cfg['suffix']}"

    # 从分析数据找图片 block id
    if not os.path.exists(ANALYSIS):
        raise RuntimeError("请先运行 analyze_page.py")
    with open(ANALYSIS, encoding="utf-8") as f:
        data = json.load(f)
    target = next((im for im in data["images"] if im["n"] == num), None)
    if not target:
        print(f"未找到图片 #{num}")
        sys.exit(1)
    img_id = target["block_id"]

    # 找到图片所在父块（遍历所有顶层块的子块）
    top = api.children(page_id)
    parent_id, children, idx = None, None, -1
    for b in top:
        if b.get("has_children"):
            subs = api.children(b["id"])
            hit = next((i for i, s in enumerate(subs) if s["id"] == img_id), -1)
            if hit >= 0:
                parent_id, children, idx = b["id"], subs, hit
                break
    if parent_id is None:
        print("未定位到图片所在父块，终止")
        sys.exit(1)

    # 防重复：如果前一个块已经是我们要插的文字，跳过
    if idx > 0 and api.rich_text(children[idx - 1]).strip() == final_text.strip():
        print(f"图片 #{num} 前已有相同注释，跳过")
        return

    prev_id = children[idx - 1]["id"] if idx > 0 else None
    block = make_block(final_text, cfg["block_type"])
    if prev_id:
        ok, data2 = api.insert_after(parent_id, prev_id, block)
    else:
        ok, data2 = api.request("PATCH", f"/blocks/{parent_id}/children", {"children": [block]})
    if ok:
        print(f"✅ 已在图片 #{num} 前插入 [{cfg['block_type']}] {final_text}")
    else:
        print(f"❌ 插入失败: {data2}")
        sys.exit(1)


if __name__ == "__main__":
    main()
