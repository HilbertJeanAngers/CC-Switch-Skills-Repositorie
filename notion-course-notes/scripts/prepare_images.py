"""下载页面图片并生成带编号的拼版，供 AI 逐张识别内容。
用法:
  python prepare_images.py                 # 下载分析脚本产出的全部裸图
  python prepare_images.py 1 2 3           # 只下载指定编号
输出目录: %TEMP%/notion_notes_imgs/
依赖: Pillow (pip install Pillow)
"""
import sys
import os
import json
import urllib.request
from PIL import Image, ImageDraw, ImageFont

TMP = os.environ.get("TEMP", "/tmp")
ANALYSIS = os.path.join(TMP, "notion_page_analysis.json")
OUTDIR = os.path.join(TMP, "notion_notes_imgs")


def load_manifest():
    if not os.path.exists(ANALYSIS):
        raise RuntimeError("未找到分析数据，请先运行 analyze_page.py")
    with open(ANALYSIS, encoding="utf-8") as f:
        return json.load(f)


def font(size, bold=False):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    try:
        return ImageFont.truetype("C:/Windows/Fonts/" + name, size)
    except Exception:
        return ImageFont.load_default()


def main():
    data = load_manifest()
    imgs = data["images"]
    wanted = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else None
    targets = [im for im in imgs if (wanted is None or im["n"] in wanted) and im.get("url")]
    os.makedirs(OUTDIR, exist_ok=True)

    # 清理旧图
    for f in os.listdir(OUTDIR):
        if f.startswith("img_") and f.endswith(".jpg"):
            os.remove(os.path.join(OUTDIR, f))

    ok = 0
    for m in targets:
        try:
            req = urllib.request.Request(m["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                buf = r.read()
            path = os.path.join(OUTDIR, f"img_{m['n']:03d}.jpg")
            with open(path, "wb") as f:
                f.write(buf)
            ok += 1
        except Exception as e:
            print(f"  下载失败 #{m['n']}: {e}")
    print(f"下载成功 {ok}/{len(targets)} -> {OUTDIR}")

    # 拼版：每 24 张一张，编号 + 已有说明
    files = sorted([f for f in os.listdir(OUTDIR) if f.startswith("img_") and f.endswith(".jpg")])
    label_map = {m["n"]: m.get("label", "") for m in imgs}
    CELL_W, CELL_H, THUMB_W, THUMB_H, COLS, PER = 300, 235, 290, 175, 4, 24
    ROWS = (PER + COLS - 1) // COLS
    for si in range(0, len(files), PER):
        batch = files[si:si + PER]
        sheet = Image.new("RGB", (COLS * CELL_W + 20, ROWS * CELL_H + 20), (245, 245, 245))
        d = ImageDraw.Draw(sheet)
        for idx, fn in enumerate(batch):
            num = int(fn.replace("img_", "").replace(".jpg", ""))
            r, c = divmod(idx, COLS)
            x, y = 10 + c * CELL_W, 10 + r * CELL_H
            try:
                im = Image.open(os.path.join(OUTDIR, fn)).convert("RGB")
                im.thumbnail((THUMB_W, THUMB_H))
                sheet.paste(im, (x + (CELL_W - im.width) // 2, y + 24))
            except Exception:
                d.text((x + 10, y + 50), "LOAD FAIL", fill=(200, 0, 0), font=font(16))
            d.text((x + 6, y + 3), f"#{num}", fill=(180, 0, 0), font=font(18, True))
            lab = label_map.get(num, "")
            if lab:
                d.text((x + 6, y + 202), lab[:18], fill=(0, 0, 0), font=font(15))
        sp = os.path.join(OUTDIR, f"sheet_{si // PER + 1}.jpg")
        sheet.save(sp, quality=85)
        print("拼版:", sp)

    # 放大单张（供看不清时细看）
    for fn in files:
        num = int(fn.replace("img_", "").replace(".jpg", ""))
        try:
            im = Image.open(os.path.join(OUTDIR, fn)).convert("RGB")
            w, h = im.size
            scale = 1100 / w
            im2 = im.resize((1100, int(h * scale)))
            canvas = Image.new("RGB", (im2.width, im2.height + 34), (255, 255, 255))
            canvas.paste(im2, (0, 34))
            ImageDraw.Draw(canvas).text((8, 4), "#" + str(num), fill=(200, 0, 0), font=font(22, True))
            canvas.save(os.path.join(OUTDIR, f"zoom_{num:03d}.png"))
        except Exception:
            pass
    print("完成。用看图工具查看 sheet_*.jpg 拼版；字太小则看 zoom_*.png 单张放大。")
    return OUTDIR


if __name__ == "__main__":
    main()
