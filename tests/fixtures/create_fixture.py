"""Create a fixture EPUB for integration tests.

The fixture is a minimal EPUB2 with 3 chapters of Chinese text,
1 image placeholder, and 1 CSS stylesheet.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


def create_fixture_epub(path: str | Path) -> Path:
    """Create a fixture EPUB with Chinese text in 3 chapters."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    META_INF_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    # CSS stylesheet
    CSS_CONTENT = """body {
    font-family: serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 1em;
}

h1 {
    font-size: 1.5em;
    margin-top: 1.5em;
}

h2 {
    font-size: 1.2em;
    margin-top: 1.2em;
}

blockquote {
    margin-left: 1em;
    padding-left: 1em;
    border-left: 3px solid #ccc;
}
"""

    # Chapter 1 — introduction
    CHAPTER_1 = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
<head>
  <meta charset="UTF-8"/>
  <title>第一章</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h1>第一章：三体世界</h1>
  <p>这是一个关于宇宙的故事。在浩瀚的星空中，隐藏着人类从未想象的秘密。</p>
  <p>三体问题困扰了人类数百年。三个太阳的无规则运动，使得三体世界的气候极端变幻无常。</p>
  <blockquote>
    <p>宇宙很大，生活更大。—— 叶文洁</p>
  </blockquote>
  <h2>红色警戒</h2>
  <p>红色的警戒灯光闪烁在基地的走廊里。叶文洁站在窗前，凝视着远处的红岸基地。</p>
  <p>她知道，自己即将做出的决定，将永远改变人类的命运。</p>
</body>
</html>"""

    # Chapter 2 — the countdown
    CHAPTER_2 = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
<head>
  <meta charset="UTF-8"/>
  <title>第二章</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h1>第二章：倒计时</h1>
  <p>倒计时开始了。三体舰队以光速的百分之五向地球驶来。</p>
  <p>人类的世界陷入了混乱。有人相信联合政府能够拯救人类，有人则认为一切努力都是徒劳。</p>
  <p>汪淼站在纳米材料的实验室里，看着那些闪闪发光的硅球。他知道，这些微小的结构背后，隐藏着三体文明的真正意图。</p>
  <h2>宇宙的黑暗森林</h2>
  <p>黑暗森林法则揭示了宇宙的残酷真相：每个文明都是带枪的猎人，在黑暗中默默前行。</p>
  <p>任何暴露自己存在的文明都将很快被消灭。这是宇宙社会学的两条公理之一。</p>
</body>
</html>"""

    # Chapter 3 — the answer
    CHAPTER_3 = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
<head>
  <meta charset="UTF-8"/>
  <title>第三章</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h1>第三章：回答</h1>
  <p>回答来了。来自四光年外的三体世界，跨越了漫长的星际空间。</p>
  <p>这里没有战争，也没有和平。只有生存。</p>
  <p>叶文洁在红岸基地的深处，看着屏幕上跳动的信号。她等待了二十七年，终于等到了这一刻。</p>
  <blockquote>
    <p>不要回答！不要回答！不要回答！—— 常伟思</p>
  </blockquote>
  <h2>新的时代</h2>
  <p>人类的历史从此进入了新的篇章。一个充满未知与危险的新时代。</p>
  <p>三体世界不再是一个遥远的传说。它就在眼前，带着毁灭与救赎的双重使命。</p>
  <p>宇宙的尺度上，人类不过是一粒微尘。但在这一粒微尘中，蕴含着无限的可能。</p>
</body>
</html>"""

    # Content.opf (EPUB2 format)
    CONTENT_OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>三体</dc:title>
    <dc:creator>刘慈欣</dc:creator>
    <dc:language>zh</dc:language>
    <dc:identifier id="BookId">urn:uuid:swatl-fixture</dc:identifier>
    <dc:description>A fixture EPUB for testing swatl translation.</dc:description>
  </metadata>
  <manifest>
    <item id="chapter1" href="text/ch01.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter2" href="text/ch02.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter3" href="text/ch03.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"/>
    <item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="toc">
    <itemref idref="chapter1"/>
    <itemref idref="chapter2"/>
    <itemref idref="chapter3"/>
  </spine>
</package>"""

    # NCX TOC
    NCX_TOC = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:uuid:swatl-fixture"/></head>
  <docTitle><text>三体</text></docTitle>
  <navMap>
    <navPoint id="nav1" playOrder="1">
      <navLabel><text>第一章：三体世界</text></navLabel>
      <content src="text/ch01.xhtml"/>
    </navPoint>
    <navPoint id="nav2" playOrder="2">
      <navLabel><text>第二章：倒计时</text></navLabel>
      <content src="text/ch02.xhtml"/>
    </navPoint>
    <navPoint id="nav3" playOrder="3">
      <navLabel><text>第三章：回答</text></navLabel>
      <content src="text/ch03.xhtml"/>
    </navPoint>
  </navMap>
</ncx>"""

    # nav.xhtml (EPUB3 nav doc — included for compatibility)
    NAV_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
<head><title>导航</title></head>
<body>
  <nav epub:type="toc">
    <h1>目录</h1>
    <ol>
      <li><a href="text/ch01.xhtml">第一章：三体世界</a></li>
      <li><a href="text/ch02.xhtml">第二章：倒计时</a></li>
      <li><a href="text/ch03.xhtml">第三章：回答</a></li>
    </ol>
  </nav>
</body>
</html>"""

    # A minimal 1x1 red pixel PNG (base64-decoded in the ZIP)
    MINIMAL_PNG = bytes(
        [
            0x89,
            0x50,
            0x4E,
            0x47,
            0x0D,
            0x0A,
            0x1A,
            0x0A,  # PNG signature
            0x00,
            0x00,
            0x00,
            0x0D,
            0x49,
            0x48,
            0x44,
            0x52,  # IHDR chunk len + type
            0x00,
            0x00,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x01,  # 1x1
            0x08,
            0x02,
            0x00,
            0x00,
            0x00,
            0x90,
            0x77,
            0x53,  # 8-bit RGB
            0xDE,
            0x00,
            0x00,
            0x00,
            0x0C,
            0x49,
            0x44,
            0x41,  # IDAT chunk
            0x54,
            0x08,
            0xD7,
            0x63,
            0xF8,
            0xFF,
            0xFF,
            0xFF,
            0x00,
            0x05,
            0xFE,
            0x02,
            0xFE,
            0xA7,
            0x96,
            0x94,
            0xA1,
            0x00,
            0x00,
            0x00,
            0x00,
            0x49,
            0x45,
            0x4E,  # IEND chunk
            0x44,
            0xAE,
            0x42,
            0x60,
            0x82,
        ]
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", META_INF_CONTAINER)
        zf.writestr("content.opf", CONTENT_OPF)
        zf.writestr("style.css", CSS_CONTENT)
        zf.writestr("toc.ncx", NCX_TOC)
        zf.writestr("nav.xhtml", NAV_XHTML)
        zf.writestr("text/ch01.xhtml", CHAPTER_1)
        zf.writestr("text/ch02.xhtml", CHAPTER_2)
        zf.writestr("text/ch03.xhtml", CHAPTER_3)
        zf.writestr("images/cover.png", MINIMAL_PNG)

    return path


def create_epub3_fixture(path: str | Path) -> Path:
    """Create a minimal EPUB3 fixture with a navigation document in the manifest.

    The nav document is *not* in the spine (which is the normal EPUB3 layout),
    so it exercises extra-document segmentation.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    chapter = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
<head><meta charset="UTF-8"/><title>第一章</title></head>
<body>
  <h1>第一章：三体世界</h1>
  <p>这是一个关于宇宙的故事。</p>
  <p>三体问题困扰了人类数百年。</p>
</body>
</html>"""

    nav = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="zh" lang="zh">
<head><meta charset="UTF-8"/><title>目录</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目录</h1>
    <ol>
      <li><a href="text/ch01.xhtml">第一章：三体世界</a></li>
    </ol>
  </nav>
</body>
</html>"""

    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>三体</dc:title>
    <dc:creator>刘慈欣</dc:creator>
    <dc:language>zh</dc:language>
    <dc:identifier id="BookId">urn:uuid:swatl-fixture3</dc:identifier>
  </metadata>
  <manifest>
    <item id="chapter1" href="text/ch01.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("content.opf", opf)
        zf.writestr("nav.xhtml", nav)
        zf.writestr("text/ch01.xhtml", chapter)

    return path
