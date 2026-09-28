"""Local review visuals; magnification reveals source pixels, never restores detail."""

from html import escape

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


def contact_sheet(items, path):
    sheet = Image.new("RGB", (1020, 390 * ((len(items) + 2) // 3)), "#f7f7f2")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(items):
        x, y = (index % 3) * 340, (index // 3) * 390
        draw.text((x + 8, y + 8), label, fill="black")
        if image.mode == "RGBA":
            image = Image.alpha_composite(Image.new("RGBA", image.size, "#dddddd"), image)
        preview = ImageOps.contain(image.convert("RGB"), (330, 350))
        sheet.paste(preview, (x + 5, y + 32))
    sheet.save(path)


def render_review(output, originals, profile):
    panels, details = [], []
    for kind, original in originals.items():
        with Image.open(output / (kind + "-subject.png")) as image:
            subject = image.copy()
        alpha = subject.getchannel("A")
        outline = ImageChops.subtract(
            alpha.filter(ImageFilter.MaxFilter(3)), alpha.filter(ImageFilter.MinFilter(3))
        )
        edge = original.copy()
        ink = Image.new("RGBA", original.size, (255, 0, 80, 0))
        ink.putalpha(outline)
        edge = Image.alpha_composite(edge, ink)
        edge.save(output / (kind + "-edges.png"))
        dark = Image.alpha_composite(Image.new("RGBA", original.size, "#24354b"), subject)
        light = Image.alpha_composite(Image.new("RGBA", original.size, "#f4d7b7"), subject)
        dark.save(output / (kind + "-dark.png"))
        light.save(output / (kind + "-light.png"))
        with Image.open(output / (kind + "-transformed.png")) as image:
            transformed = image.copy()
        panels.extend(
            [
                (kind + " ORIGINAL", original),
                (kind + " ALPHA", alpha),
                (kind + " EDGES / PENDING", edge),
                (kind + " DARK", dark),
                (kind + " LIGHT", light),
                (kind + " TRANSFORMED", transformed),
            ]
        )
        detail_panels = []
        for index, (name, box) in enumerate(profile[kind]["regions"].items()):
            for label, image in (("original", original), ("dark", dark), ("edge", edge)):
                crop = image.crop(tuple(box))
                crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.NEAREST)
                filename = f"{kind}-detail-{index}-{label}.png"
                crop.save(output / filename)
                detail_panels.append((name + " / " + label + " / 3x NEAREST", crop))
                details.append(
                    f'<figure><img src="{filename}"><figcaption>'
                    f"{escape(kind + ' / ' + name + ' / ' + label)}：3倍像素放大，待确认"
                    "</figcaption></figure>"
                )
        contact_sheet(detail_panels, output / (kind + "-details.png"))
    contact_sheet(panels, output / "comparison.png")
    (output / "review.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>真实样本审查</title>'
        "<style>body{font:18px sans-serif;max-width:1100px;margin:30px auto;line-height:1.7}"
        "img{max-width:100%;background:#ddd}figure{display:inline-block;vertical-align:top;"
        "max-width:46%;margin:12px}a{margin-right:20px}</style>"
        f"<h1>{escape(profile['sample_id'])} · 所有视觉审核待确认</h1>"
        "<p>真实低分辨率样本实验。非已验收成品；放大不增加原始细节。"
        "参考图仅登记，不作为主体、背景、人物、Logo 或文案来源。</p>"
        '<p><a href="manifest.json">来源、哈希与参数</a><a href="profile.json">重放配置</a>'
        '<a href="product-subject.png">商品透明图</a><a href="gift-subject.png">赠品透明图</a>'
        '<a href="originals/product.png">商品原文件</a>'
        '<a href="originals/gift.png">赠品原文件</a></p>'
        '<h2>原图 / alpha / 边缘 / 深浅底 / 变换</h2><img src="comparison.png">'
        '<h2>确定性合成实验，非参考图复刻</h2><img src="composite.png">'
        '<p><a href="composite.png">PNG</a><a href="composite.jpg">JPEG</a></p>'
        "<h2>关键部位逐项检查</h2><p>核对狮子图案、印花、孔洞、细带、浅色护角边缘、"
        "叠放数量与形状、右上画面文字分离、底部阴影；有问题请按区域名反馈。</p>"
        + "".join(details)
        + "</html>",
        encoding="utf-8",
    )
