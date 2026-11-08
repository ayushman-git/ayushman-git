"""Builds the profile README and its images in assets/.

The page is one plain column. Each section is an SVG with only the glyphs it
uses embedded as WOFF2, so the type renders the same everywhere GitHub shows
an image. Every section is written twice, for GitHub's light and dark themes.

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
    "sans": ("Geist-Variable.ttf", 400, "Helvetica, Arial, sans-serif"),
    "medium": ("Geist-Variable.ttf", 500, "Helvetica, Arial, sans-serif"),
    "mono": ("GeistMono-Variable.ttf", 400, "Menlo, monospace"),
}


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


def measure(text, font, size):
    face = F[font]
    units = sum(face["hmtx"][face["cmap"].get(ord(c), ".notdef")][0] for c in text)
    return units * size / face["upm"]


def woff2(font, chars):
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga", "calt", "tnum"]
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


W = 840
MEASURE = 600  # line length for running text


class Section:
    """One full-width image. Set .h once the content is laid out."""

    def __init__(self, theme, rule=True):
        self.c = THEMES[theme]
        self.els = []
        self.used = defaultdict(set)
        self.h = 0
        if rule:
            self.els.append(f'<line x1="0" y1="0.5" x2="{W}" y2="0.5" stroke="{self.c["rule"]}"/>')

    def text(self, x, y, s, font, size, tone="ink", anchor="start"):
        self.used[font].update(s)
        attrs = f' text-anchor="{anchor}"' if anchor != "start" else ""
        self.els.append(
            f'<text x="{x:.1f}" y="{y:.1f}" class="{font}" font-size="{size}" '
            f'fill="{self.c[tone]}"{attrs}>{escape(s)}</text>'
        )

    def label(self, y, s):
        self.text(0, y, s, "sans", 13.5, "muted")

    def meta(self, y, s, x=W):
        self.text(x, y, s, "mono", 12.5, "muted", anchor="end")

    def para(self, x, y, s, font="sans", size=16, tone="body", width=MEASURE, leading=26):
        """Wraps s inside width; returns the last baseline."""
        lines, line = [], ""
        for word in s.split():
            trial = f"{line} {word}".strip()
            if line and measure(trial, font, size) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
        for i, ln in enumerate(lines):
            self.text(x, y + i * leading, ln, font, size, tone)
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
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{self.h}" '
            f'viewBox="0 0 {W} {self.h}" role="img" aria-label="{escape(title)}">'
            f"<title>{escape(title)}</title><style>{''.join(faces)}</style>"
            + "".join(self.els)
            + "</svg>\n"
        )


INTRO = [
    "I’m making Seqora, a database client, because every one I used took ages to open. "
    "Before that, Stash, for the articles I save and never read. Day job at Skillsoft, in edtech.",
    "When I’m not building, I’m reading about astronomy or sketching ideas to think better.",
]


def intro(theme):
    s = Section(theme, rule=False)
    s.text(0, 22, "Ayushman Gupta", "medium", 17)
    s.text(0, 46, "Full-stack engineer in Hyderabad, India", "sans", 15, "muted")
    y = s.para(0, 92, INTRO[0])
    y = s.para(0, y + 40, INTRO[1])
    s.h = round(y + 22)
    return s.svg("Ayushman Gupta, full-stack engineer in Hyderabad, India. " + " ".join(INTRO))


# The Seqora mark, from apps/desktop/src/lib/components/brand/SeqoraMark.svelte
# (viewBox 3 12 108 108). The index drops into place once, as it does on launch.
MARK_FRAME = "M12 12H96V30H30V84H84V48H102V102H12Z"
MARK_INDEX = "M84 101H102V120H84Z"

SEQORA = (
    "A desktop database client for PostgreSQL, MySQL, MariaDB, SQLite and SQL Server. "
    "No account, no cloud in the middle. Your queries go straight from your machine to "
    "your database. I make it on my own. There is no team."
)
QUESTIONS = [
    "Which connection am I on?",
    "Will this change data?",
    "What just ran?",
    "How does this table relate to that one?",
]


def seqora(theme):
    s = Section(theme)
    s.label(44, "Projects")
    size = 15
    ink = s.c["ink"]
    s.raw(
        f'<g transform="translate(0 {98 - size + 2}) scale({size / 108:.4f}) translate(-3 -12)" fill="{ink}">'
        f'<path d="{MARK_FRAME}"/>'
        f'<path d="{MARK_INDEX}"><animate attributeName="opacity" values="0;0;1" keyTimes="0;0.5;1" '
        f'dur="0.9s"/><animateTransform attributeName="transform" type="translate" '
        f'values="0 -18;0 -18;0 0" keyTimes="0;0.5;1" dur="0.9s" calcMode="spline" '
        f'keySplines="0 0 1 1;0.2 0.8 0.2 1"/></path></g>'
    )
    s.text(24, 99, "Seqora", "medium", 16.5)
    s.meta(99, "seqora.dev")
    y = s.para(0, 126, SEQORA, width=MEASURE)
    s.meta(126, "Rust · Svelte · Tauri")
    s.meta(152, "since July 2026")
    s.label(y + 50, "The four questions")
    for i, q in enumerate(QUESTIONS):
        s.text(0, y + 92 + i * 34, q, "italic", 26)
    s.h = round(y + 92 + 3 * 34 + 26)
    return s.svg(
        "Projects. Seqora, since July 2026, built with Rust, Svelte and Tauri: " + SEQORA
        + " The four questions: " + " ".join(QUESTIONS)
    )


def project(theme, name, blurb, meta, meta2):
    s = Section(theme, rule=False)
    s.text(0, 24, name, "medium", 16.5)
    s.meta(24, meta)
    y = s.para(0, 51, blurb)
    s.meta(51, meta2)
    s.h = round(y + 16)
    return s.svg(f"{name}. {blurb} {meta}, {meta2}.")


def stash(theme):
    return project(
        theme,
        "Stash",
        "For the articles I save and never read. Save from the terminal, read offline later.",
        "Rust · SQLite",
        "command line",
    )


def astronomia(theme):
    return project(
        theme,
        "Astronomia",
        "A Discord bot for astronomers. Launches, the sky and moon for where you are, "
        "and the astronomy picture of the day.",
        "discord.js · Firebase",
        "2020",
    )


def fetch_posts():
    with urllib.request.urlopen(FEED, timeout=20) as res:
        feed = res.read().decode("utf-8", "replace")
    posts = []
    for item in re.findall(r"<item>([\s\S]*?)</item>", feed):
        def field(tag):
            m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</{tag}>", item)
            return unescape(m.group(1)).strip() if m else ""

        posts.append(
            {
                "title": field("title"),
                "link": field("link"),
                "date": parsedate_to_datetime(field("pubDate")).strftime("%Y-%m-%d"),
            }
        )
    return posts


def writing(theme, posts):
    s = Section(theme)
    s.label(44, "Writing")
    s.meta(44, "ayushman.dev/blog")
    y = 96
    year = None
    for p in posts[:8]:
        yr, month, day = p["date"].split("-")
        if yr != year:
            if year is not None:
                y += 14
            s.text(0, y, yr, "mono", 12.5, "muted")
            year = yr
        last = s.para(96, y, p["title"], font="serif", size=21, tone="ink", width=560, leading=26)
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        s.meta(y, f"{int(day)} {months[int(month) - 1]}")
        y = last + 40
    s.h = round(y - 40 + 22)
    return s.svg("Writing from ayushman.dev: " + "; ".join(p["title"] for p in posts[:8]) + ".")


LINKS = {
    "seqora": "https://seqora.dev",
    "stash": "https://github.com/ayushman-git/stash",
    "astronomia": "https://ayushman-git.github.io/astronomia-site/",
    "writing": "https://www.ayushman.dev/blog/",
}


def picture(name, alt):
    tag = (
        "<picture>"
        f'<source media="(prefers-color-scheme: dark)" srcset="assets/{name}.dark.svg">'
        f'<img src="assets/{name}.light.svg" width="100%" alt="{escape(alt, {chr(34): "&quot;"})}">'
        "</picture>"
    )
    return f'<a href="{LINKS[name]}">{tag}</a>' if name in LINKS else tag


def readme(alts, order):
    return (
        "<!-- Generated by scripts/build.py. Edit the copy there and rebuild; don't edit the SVGs. -->\n\n"
        + "\n\n".join(f"<p>\n{picture(n, alts[n])}\n</p>" for n in order)
        + '\n\n<p><sub><a href="https://ayushman.dev">ayushman.dev</a> · '
        '<a href="https://seqora.dev">seqora.dev</a> · '
        '<a href="https://www.linkedin.com/in/ayushman-git/">LinkedIn</a></sub></p>\n'
    )


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

    sections = {
        "intro": intro,
        "seqora": seqora,
        "stash": stash,
        "astronomia": astronomia,
        "writing": lambda t: writing(t, posts),
    }
    for old in ASSETS.glob("*.svg"):
        if old.name.split(".")[0] not in sections:
            old.unlink()
    alts = {}
    for name, build in sections.items():
        for theme in THEMES:
            out = ASSETS / f"{name}.{theme}.svg"
            svg = build(theme)
            out.write_text(svg)
            alts[name] = unescape(re.search(r"<title>(.*?)</title>", svg).group(1))
            print(f"{out.relative_to(ROOT)}  {out.stat().st_size / 1024:.1f} KB")
    (ROOT / "README.md").write_text(readme(alts, list(sections)))


if __name__ == "__main__":
    main()
