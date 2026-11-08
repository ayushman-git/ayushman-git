"""Builds the profile README cards in assets/.

Each card is an SVG with only the glyphs it uses embedded as WOFF2, so the
typography renders the same everywhere GitHub shows an image. Every card is
written twice, for GitHub's light and dark themes.

    pip install fonttools brotli
    python scripts/build.py            # fetch the latest posts, then build
    python scripts/build.py --offline  # build from assets/posts.json
"""

import base64
import io
import json
import re
import sys
import urllib.request
from collections import defaultdict
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
ASSETS = ROOT / "assets"
FEED = "https://www.ayushman.dev/api/rss"

THEMES = {
    "dark": {"ink": "#F0EDE6", "body": "#A9A49B", "muted": "#6F6B64", "rule": "#262B33"},
    "light": {"ink": "#1B1A17", "body": "#57534C", "muted": "#8C877E", "rule": "#E4E0D8"},
}

# key: (file, weight for variable fonts, CSS fallback)
FACES = {
    "serif": ("InstrumentSerif-Regular.ttf", None, "Georgia, serif"),
    "italic": ("InstrumentSerif-Italic.ttf", None, "Georgia, serif"),
    "sans": ("Geist-Variable.ttf", 300, "Helvetica, Arial, sans-serif"),
    "medium": ("Geist-Variable.ttf", 400, "Helvetica, Arial, sans-serif"),
    "mono": ("GeistMono-Variable.ttf", 400, "Menlo, monospace"),
}

LABEL = {"font": "mono", "size": 10.5, "ls": 1.5, "tone": "muted"}


def load_faces():
    faces = {}
    for key, (file, weight, _) in FACES.items():
        font = TTFont(FONTS / file, recalcTimestamp=False)
        if weight is not None:
            font = instantiateVariableFont(font, {"wght": weight})
        buf = io.BytesIO()
        font.save(buf)
        faces[key] = {
            "bytes": buf.getvalue(),
            "upm": font["head"].unitsPerEm,
            "cmap": font.getBestCmap(),
            "hmtx": font["hmtx"],
        }
    return faces


F = load_faces()


def measure(text, font, size, ls=0.0):
    face = F[font]
    units = sum(face["hmtx"][face["cmap"].get(ord(c), ".notdef")][0] for c in text)
    return units * size / face["upm"] + ls * len(text)


def woff2(font, chars):
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga", "calt"]
    options.name_IDs = []
    options.notdef_outline = True
    options.drop_tables += ["meta"]
    sub = subset.Subsetter(options)
    sub.populate(unicodes={ord(c) for c in chars} | {0x20})
    tt = TTFont(io.BytesIO(F[font]["bytes"]), recalcTimestamp=False)
    sub.subset(tt)
    out = io.BytesIO()
    tt.flavor = "woff2"
    tt.save(out)
    return base64.b64encode(out.getvalue()).decode()


class Card:
    def __init__(self, width, height, theme, frame=True):
        self.w, self.h = width, height
        self.c = THEMES[theme]
        self.els = []
        self.used = defaultdict(set)
        if frame:
            self.els.append(
                f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="14" '
                f'fill="none" stroke="{self.c["rule"]}"/>'
            )

    def text(self, x, y, s, font, size, tone="ink", anchor="start", ls=0.0):
        self.used[font].update(s)
        attrs = f' text-anchor="{anchor}"' if anchor != "start" else ""
        if ls:
            attrs += f' letter-spacing="{ls}"'
            if anchor == "end":
                x += ls  # letter-spacing trails the last glyph
        self.els.append(
            f'<text x="{x:.1f}" y="{y:.1f}" class="{font}" font-size="{size}" '
            f'fill="{self.c[tone]}"{attrs}>{escape(s)}</text>'
        )

    def label(self, x, y, s, anchor="start", tone="muted"):
        self.text(x, y, s.upper(), LABEL["font"], LABEL["size"], tone, anchor, LABEL["ls"])

    def rule(self, x1, y1, x2, y2):
        self.els.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{self.c["rule"]}"/>'
        )

    def rich(self, x, y, runs, max_width, leading):
        """Wraps runs of (text, font, size, tone) inside max_width; returns the last baseline."""
        words = []
        for text, font, size, tone in runs:
            for piece in re.findall(r"\S+\s*", text):
                words.append((piece, font, size, tone))
        lines, line, used = [], [], 0.0
        for piece, font, size, tone in words:
            word_w = measure(piece.rstrip(), font, size)
            if line and used + word_w > max_width:
                lines.append(line)
                line, used = [], 0.0
            line.append((piece, font, size, tone))
            used += measure(piece, font, size)
        if line:
            lines.append(line)
        for i, line in enumerate(lines):
            spans = []
            merged = []
            for piece, font, size, tone in line:
                if merged and merged[-1][1:] == (font, size, tone):
                    merged[-1] = (merged[-1][0] + piece, font, size, tone)
                else:
                    merged.append((piece, font, size, tone))
            if merged:
                last = merged[-1]
                merged[-1] = (last[0].rstrip(),) + last[1:]
            for piece, font, size, tone in merged:
                self.used[font].update(piece)
                spans.append(
                    f'<tspan class="{font}" font-size="{size}" fill="{self.c[tone]}">'
                    f"{escape(piece)}</tspan>"
                )
            self.els.append(
                f'<text x="{x}" y="{y + i * leading:.1f}" style="white-space:pre">{"".join(spans)}</text>'
            )
        return y + (len(lines) - 1) * leading

    def raw(self, markup):
        self.els.append(markup)

    def svg(self, title):
        faces = []
        for font, chars in sorted(self.used.items()):
            faces.append(
                f'@font-face{{font-family:"{font}";src:url(data:font/woff2;base64,{woff2(font, chars)}) '
                f'format("woff2")}}.{font}{{font-family:"{font}",{FACES[font][2]}}}'
            )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(title)}">'
            f"<title>{escape(title)}</title><style>{''.join(faces)}</style>"
            + "".join(self.els)
            + "</svg>\n"
        )


W = 840
HALF = 413


def hero(theme):
    c = Card(W, 300, theme)
    c.label(36, 54, "Full-stack engineer  ·  India")
    c.text(31, 132, "Ayushman Gupta", "serif", 68)
    c.rich(
        34,
        182,
        [
            ("I build the tools I got ", "sans", 16.5, "body"),
            ("tired of waiting for", "italic", 20, "ink"),
            (
                ": a database client, and a reading list that lives in my terminal. "
                "By day, I build learning software at Skillsoft.",
                "sans",
                16.5,
                "body",
            ),
        ],
        440,
        27,
    )
    c.rule(540, 36, 540, 264)
    rows = [
        ("Now", "Shipping Seqora"),
        ("Day job", "Skillsoft, edtech"),
        ("Learning", "Rust, agent workflows"),
        ("Off hours", "Astronomy, sketching"),
    ]
    for i, (k, v) in enumerate(rows):
        top = 36 + i * 57
        if i:
            c.rule(568, top, 806, top)
        c.label(568, top + 22, k)
        c.text(568, top + 44, v, "medium", 14.5)
    return c.svg(
        "Ayushman Gupta. Full-stack engineer in India. I build the tools I got tired of waiting "
        "for: a database client, and a reading list that lives in my terminal. By day, I build "
        "learning software at Skillsoft. Now shipping Seqora; learning Rust and agent workflows; "
        "off hours, astronomy and sketching."
    )


SEQORA_MARK = "M12 12H96V30H30V84H84V48H102V102H12Z M84 101H102V120H84Z"


def seqora(theme):
    c = Card(W, 352, theme)
    c.label(34, 54, "01  ·  Seqora.dev")
    c.label(508, 54, "2026 — now", anchor="end")
    c.text(31, 122, "Seqora", "serif", 52)
    c.rich(
        34,
        162,
        [
            (
                "A desktop database client for PostgreSQL, MySQL, MariaDB, SQLite and "
                "SQL Server. It opens fast, needs no account, and keeps your data between "
                "your machine and your database.",
                "sans",
                16.5,
                "body",
            )
        ],
        450,
        27,
    )
    facts = [("Built with", "Rust, Svelte, Tauri"), ("Runs on", "macOS, Windows"), ("Made by", "Just me, since July")]
    c.rule(34, 268, 508, 268)
    for i, (k, v) in enumerate(facts):
        x = 34 + i * 160
        c.label(x, 294, k)
        c.text(x, 318, v, "medium", 14)
    c.rule(540, 36, 540, 318)
    s = 26 / 108
    c.raw(
        f'<path d="{SEQORA_MARK}" fill="{c.c["ink"]}" '
        f'transform="translate(780 34) scale({s:.4f}) translate(-3 -12)"/>'
    )
    c.label(568, 54, "Four questions it answers")
    qs = ["Which connection am I on?", "Will this change data?", "What just ran?", "How does this table relate", "to that one?"]
    for i, q in enumerate(qs):
        c.text(568, 106 + i * 31, q, "italic", 21)
    c.label(806, 318, "seqora.dev ↗", anchor="end", tone="body")
    return c.svg(
        "Seqora, my main project since July 2026: a desktop database client for PostgreSQL, "
        "MySQL, MariaDB, SQLite and SQL Server, built alone with Rust, Svelte and Tauri for "
        "macOS and Windows. It answers four questions: which connection am I on, will this "
        "change data, what just ran, and how does this table relate to that one."
    )


def project(theme, number, kind, name, blurb, stack, cta):
    c = Card(HALF, 236, theme)
    c.label(30, 50, number)
    c.label(HALF - 30, 50, kind, anchor="end")
    c.text(28, 108, name, "serif", 40)
    c.rich(30, 144, [(blurb, "sans", 15, "body")], HALF - 64, 24)
    c.rule(30, 186, HALF - 30, 186)
    c.label(30, 212, stack)
    c.label(HALF - 30, 212, cta, anchor="end", tone="body")
    return c.svg(f"{name}. {blurb} {stack.title()}.")


def stash(theme):
    return project(
        theme,
        "02",
        "Rust  ·  CLI",
        "Stash",
        "Save an article from the terminal, read it offline later. Starts in under 50 ms.",
        "SQLite  ·  Local-first",
        "repo ↗",
    )


def astronomia(theme):
    return project(
        theme,
        "03",
        "Discord bot",
        "Astronomia",
        "A Discord bot for astronomers: space news, celestial objects, and the odd film pick.",
        "discord.js  ·  Puppeteer",
        "site ↗",
    )


NOTES = [
    "Fix the small, annoying things first. They’re the ones people hit every day.",
    "Use what you build every day. It tells you what to build next.",
    "Keep people’s data on their own machine when you can.",
]


def notes(theme):
    c = Card(W, 236, theme)
    c.label(34, 54, "Notes to self")
    col = (W - 68) / 3
    for i, note in enumerate(NOTES):
        x = 34 + i * col
        if i:
            c.rule(x - 18, 84, x - 18, 204)
        c.text(x, 106, ["i.", "ii.", "iii."][i], "italic", 19, "muted")
        c.rich(x + 30, 106, [(note, "serif", 21, "ink")], col - 70, 28)
    return c.svg("Notes to self. " + " ".join(NOTES))


CATEGORY = {
    "devlog": "Devlog",
    "space-software": "Space × software",
    "technical-guide": "Guide",
    "case-study": "Case study",
}


def fetch_posts():
    with urllib.request.urlopen(FEED, timeout=20) as res:
        feed = res.read().decode("utf-8", "replace")
    posts = []
    for item in re.findall(r"<item>([\s\S]*?)</item>", feed):
        def field(tag):
            m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</{tag}>", item)
            return unescape(m.group(1)).strip() if m else ""

        link = field("link")
        kind = link.rstrip("/").split("/")[-2] if "/blog/" in link else ""
        posts.append(
            {
                "title": field("title"),
                "link": link,
                "date": parsedate_to_datetime(field("pubDate")).strftime("%b %Y"),
                "kind": CATEGORY.get(kind, kind.replace("-", " ").capitalize()),
            }
        )
    return posts


def writing(theme, posts):
    rows = posts[:5]
    c = Card(W, 92 + 54 * len(rows), theme)
    c.label(34, 54, "Writing")
    c.label(806, 54, "ayushman.dev/blog ↗", anchor="end", tone="body")
    for i, p in enumerate(rows):
        top = 76 + i * 54
        c.rule(34, top, 806, top)
        c.label(34, top + 33, p["date"])
        title = p["title"]
        while measure(title, "serif", 21) > 470:
            title = title.rsplit(" ", 1)[0].rstrip(":,") + "…"
        c.text(152, top + 34, title, "serif", 21)
        c.label(806, top + 33, p["kind"], anchor="end")
    return c.svg("Writing from ayushman.dev: " + "; ".join(p["title"] for p in rows) + ".")


def footer(theme):
    c = Card(W, 72, theme, frame=False)
    c.text(4, 44, "— a.g.", "italic", 30, "muted")
    c.label(836, 40, "Set in Instrument Serif and Geist", anchor="end")
    return c.svg("Signed a.g. Set in Instrument Serif and Geist.")


def main():
    ASSETS.mkdir(exist_ok=True)
    cache = ASSETS / "posts.json"
    posts = None
    if "--offline" not in sys.argv:
        try:
            posts = fetch_posts()
            cache.write_text(json.dumps(posts, indent=2, ensure_ascii=False) + "\n")
        except Exception as err:  # keep the last good list if the feed is down
            print(f"feed unavailable, using cache: {err}", file=sys.stderr)
    if posts is None:
        posts = json.loads(cache.read_text())

    cards = {
        "hero": hero,
        "seqora": seqora,
        "stash": stash,
        "astronomia": astronomia,
        "notes": notes,
        "writing": lambda t: writing(t, posts),
        "footer": footer,
    }
    alts = {}
    for name, build in cards.items():
        for theme in THEMES:
            out = ASSETS / f"{name}.{theme}.svg"
            svg = build(theme)
            out.write_text(svg)
            alts[name] = unescape(re.search(r"<title>(.*?)</title>", svg).group(1))
            print(f"{out.relative_to(ROOT)}  {out.stat().st_size / 1024:.1f} KB")
    (ROOT / "README.md").write_text(readme(alts))


LINKS = {
    "seqora": "https://seqora.dev",
    "stash": "https://github.com/ayushman-git/stash",
    "astronomia": "https://ayushman-git.github.io/astronomia-site/",
    "writing": "https://www.ayushman.dev/blog/",
}


def picture(name, alt, width="100%"):
    tag = (
        "<picture>"
        f'<source media="(prefers-color-scheme: dark)" srcset="assets/{name}.dark.svg">'
        f'<img src="assets/{name}.light.svg" width="{width}" alt="{escape(alt, {chr(34): "&quot;"})}">'
        "</picture>"
    )
    return f'<a href="{LINKS[name]}">{tag}</a>' if name in LINKS else tag


def readme(alts):
    half = "49.2%"
    rows = [
        picture("hero", alts["hero"]),
        picture("seqora", alts["seqora"]),
        picture("stash", alts["stash"], half) + "\n" + picture("astronomia", alts["astronomia"], half),
        picture("notes", alts["notes"]),
        picture("writing", alts["writing"]),
        picture("footer", alts["footer"]),
    ]
    return (
        "<!-- Generated by scripts/build.py. Edit the copy there and rebuild; don't edit the SVGs. -->\n\n"
        + "\n\n".join(f'<p align="center">\n{r}\n</p>' for r in rows)
        + "\n\n<p align=\"center\"><sub>"
        '<a href="https://ayushman.dev">ayushman.dev</a> · '
        '<a href="https://seqora.dev">seqora.dev</a> · '
        '<a href="https://www.linkedin.com/in/ayushman-git/">LinkedIn</a>'
        "</sub></p>\n"
    )


if __name__ == "__main__":
    main()
