#!/usr/bin/env python3
# main.py - SVN TUI browser using urwid + term-image (Kitty graphics protocol)
# pip install urwid term-image pillow pygments

import subprocess
import os
import os.path
import sys
import io
import tempfile
from typing import Optional

import urwid
from term_image.image import KittyImage
from term_image.widget import UrwidImage, UrwidImageScreen

# 强制启用 Kitty 协议（Ghostty 支持，但 term-image 自动检测可能失败）
KittyImage._forced_support = True

# Pygments 语法高亮
try:
    import pygments as _pygments_check
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

# 支持预览的图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".ico"}

# 已知的二进制文件扩展名（不支持文本预览）
BINARY_EXTENSIONS = {
    # Office 文档
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    # PDF
    ".pdf",
    # 压缩包
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    # 可执行文件 / 库
    ".exe", ".dll", ".so", ".dylib", ".a", ".o",
    # 字体
    ".ttf", ".otf", ".woff", ".woff2",
    # 音视频
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".flac", ".wav",
    # 数据库
    ".db", ".sqlite", ".sqlite3",
}

def is_image_file(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS

def is_binary_file(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in BINARY_EXTENSIONS

def sanitize_for_urwid(text: str) -> str:
    """
    清理字符串，移除会导致 urwid 渲染崩溃的字符。

    urwid 使用 wcwidth 库计算字符宽度，遇到宽度为 0 的字符（控制字符、
    零宽字符、组合字符等）时，clip/space 模式会产生 sc=0 的 LayoutSegment，
    触发 ValueError: (0, 0, 1) 崩溃。
    """
    import unicodedata
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ")
    cleaned = []
    for char in text:
        if char in ("\n", " "):
            cleaned.append(char)
            continue
        category = unicodedata.category(char)
        # Cc: 控制字符，Cf: 格式字符，Mn: 非间距组合字符，Me: 封闭组合字符
        # 这些字符的 wcwidth 返回 0 或 -1，会导致 urwid 崩溃
        if category in ("Cc", "Cf", "Mn", "Me"):
            continue
        cleaned.append(char)
    return "".join(cleaned)

# ─── SVN 操作 ────────────────────────────────────────────────────────────────

def svn_list(url: str) -> list[dict]:
    """获取 SVN 目录列表"""
    try:
        result = subprocess.run(
            ["svn", "list", "--xml", url], capture_output=True, text=True, check=True
        )
        import xml.etree.ElementTree as ET
        root = ET.fromstring(result.stdout)
        entries = []
        for entry in root.findall(".//entry"):
            kind = entry.get("kind")
            name_el = entry.find("name")
            name = (name_el.text or "") if name_el is not None else ""
            commit = entry.find("commit")
            if commit is not None:
                revision = commit.get("revision") or "-"
                author_el = commit.find("author")
                author = author_el.text or "-" if author_el is not None else "-"
                date_el = commit.find("date")
                date = (date_el.text or "")[:10] if date_el is not None else "-"
            else:
                revision = author = date = "-"
            entries.append({"kind": kind, "name": name, "revision": revision,
                            "author": author, "date": date})
        return entries
    except subprocess.CalledProcessError:
        return []


def decode_bytes(raw: bytes) -> str:
    """尝试多种编码解码字节内容，优先 UTF-8，fallback 到 GBK，最后用 latin-1 兜底"""
    for encoding in ("utf-8", "gbk", "gb2312", "big5"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # latin-1 可以解码任意字节，不会抛异常
    return raw.decode("latin-1")


def svn_cat(url: str) -> str:
    """获取 SVN 文件文本内容，自动处理非 UTF-8 编码（如 GBK）"""
    try:
        result = subprocess.run(
            ["svn", "cat", url], capture_output=True, check=True
        )
        return decode_bytes(result.stdout)
    except subprocess.CalledProcessError as error:
        error_message = error.stderr.decode("utf-8", errors="replace") if error.stderr else ""
        return f"[错误] 无法读取文件:\n{error_message}"


def svn_cat_binary(url: str) -> Optional[bytes]:
    """获取 SVN 文件二进制内容"""
    try:
        result = subprocess.run(
            ["svn", "cat", url], capture_output=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


# ─── 语法高亮 ─────────────────────────────────────────────────────────────────

# Pygments Token 类型 → urwid palette 属性名映射
def _token_to_urwid_attr(token_type) -> str:
    """将 Pygments token 类型映射到 urwid palette 属性名"""
    from pygments.token import Token
    # 按优先级从具体到宽泛匹配
    if token_type in Token.Keyword or token_type in Token.Keyword.Type:
        return "syn.keyword"
    if token_type in Token.Name.Builtin or token_type in Token.Name.Builtin.Pseudo:
        return "syn.builtin"
    if token_type in Token.Name.Decorator:
        return "syn.decorator"
    if token_type in Token.Name.Class or token_type in Token.Name.Exception:
        return "syn.type"
    if token_type in Token.Literal.String or token_type in Token.String:
        return "syn.string"
    if token_type in Token.Comment:
        return "syn.comment"
    if token_type in Token.Literal.Number or token_type in Token.Number:
        return "syn.number"
    if token_type in Token.Operator or token_type in Token.Punctuation:
        return "syn.operator"
    if token_type in Token.Error:
        return "syn.error"
    return "syn.name"


def highlight_code(code: str, filename: str) -> list | str:
    """
    用 Pygments 对代码进行语法高亮，返回 urwid markup list（[(attr, text), ...]）。
    若 Pygments 不可用则返回纯文本字符串。
    """
    if not PYGMENTS_AVAILABLE:
        return code
    try:
        from pygments.lexers import get_lexer_for_filename, guess_lexer
        from pygments.lexers import TextLexer
        from pygments import lex
        try:
            lexer = get_lexer_for_filename(filename, code, stripall=False)
        except Exception:
            try:
                lexer = guess_lexer(code)
            except Exception:
                return code

        markup = []
        for token_type, token_value in lex(code, lexer):
            if not token_value:
                continue
            attr = _token_to_urwid_attr(token_type)
            markup.append((attr, token_value))
        return markup
    except Exception:
        return code


# ─── 图片加载 ─────────────────────────────────────────────────────────────────

def load_kitty_image(image_data: bytes) -> Optional[KittyImage]:
    """从二进制数据创建 KittyImage 实例"""
    try:
        from PIL import Image
        pil_image = Image.open(io.BytesIO(image_data))
        return KittyImage(pil_image)
    except Exception:
        return None


# ─── urwid 调色板 ─────────────────────────────────────────────────────────────

PALETTE = [
    ("header",       "white",       "dark blue",   "bold"),
    ("footer",       "white",       "dark blue"),
    ("focus",        "black",       "light green"),
    ("dir",          "light blue",  ""),
    ("file",         "white",       ""),
    ("border",       "dark green",  ""),
    ("preview_title","yellow",      ""),
    ("key",          "light cyan",  ""),
    ("error",        "light red",   ""),
    # Pygments 语法高亮颜色（monokai 风格）
    ("syn.keyword",    "light magenta", ""),
    ("syn.builtin",    "light cyan",    ""),
    ("syn.string",     "light green",   ""),
    ("syn.comment",    "dark gray",     ""),
    ("syn.number",     "light red",     ""),
    ("syn.operator",   "yellow",        ""),
    ("syn.name",       "white",         ""),
    ("syn.decorator",  "light blue",    ""),
    ("syn.type",       "light cyan",    ""),
    ("syn.error",      "light red",     ""),
    ("line_num",       "dark gray",     ""),
]


# ─── 主应用 ───────────────────────────────────────────────────────────────────

class SvnBrowser:
    """SVN TUI 浏览器主类"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.current_url = self.base_url
        self.history: list[str] = []
        self.entries: list[dict] = []

        # 左侧文件列表
        self.list_walker = urwid.SimpleFocusListWalker([])
        self.list_box = urwid.ListBox(self.list_walker)

        # 右侧预览区域：用 ListBox 支持滚动翻页
        self.preview_walker = urwid.SimpleFocusListWalker([urwid.Text("")])
        self.preview_list_box = urwid.ListBox(self.preview_walker)
        self.preview_pile = urwid.Pile([self.preview_list_box])

        # 当前预览的图片 widget（None 表示无图片）
        self.current_image_widget: Optional[UrwidImage] = None

        # 左侧面板（带边框和标题）
        left_panel = urwid.LineBox(
            self.list_box,
            title="📂 目录列表",
            title_align="left",
        )

        # 右侧面板（带边框和标题）
        self.right_line_box = urwid.LineBox(
            self.preview_pile,
            title="📄 文件预览",
            title_align="left",
        )

        # 左右布局，左 1/3，右 2/3
        self.columns = urwid.Columns([
            ("weight", 1, left_panel),
            ("weight", 2, self.right_line_box),
        ])

        # Header
        header_text = urwid.Text(
            [("header", " SVN Browser  "),
             ("header", " [j/k] 移动  [enter/→] 进入  [esc/←] 返回  [d/u] 预览翻页  [q] 退出")],
            align="left",
        )
        header = urwid.AttrMap(header_text, "header")

        # Footer（显示当前路径）
        self.footer_text = urwid.Text("", align="left")
        footer = urwid.AttrMap(self.footer_text, "footer")

        self.frame = urwid.Frame(
            body=self.columns,
            header=header,
            footer=footer,
        )

        # 使用 UrwidImageScreen 支持 Kitty 图片渲染
        self.screen = UrwidImageScreen()
        self.screen.set_terminal_properties(colors=256)

        self.loop = urwid.MainLoop(
            self.frame,
            palette=PALETTE,
            screen=self.screen,
            unhandled_input=self.handle_input,
        )

        # 防抖：记录待触发的预览定时器句柄
        self._preview_alarm = None

    def run(self):
        self.load_dir(self.current_url)
        self.loop.run()

    def load_dir(self, url: str):
        """加载 SVN 目录"""
        self.current_url = url
        self.footer_text.set_text([("footer", f" {url}")])

        # 清空预览
        self._clear_preview()

        # 加载目录列表
        self.entries = svn_list(url)
        self.list_walker.clear()

        if not self.entries:
            self.list_walker.append(
                urwid.Text(("error", "[ 空目录或无法访问 ]"))
            )
            return

        for entry in self.entries:
            icon = "📁" if entry["kind"] == "dir" else "📄"
            name = sanitize_for_urwid(entry["name"])
            rev = sanitize_for_urwid(entry["revision"])
            author = sanitize_for_urwid(entry["author"])
            date = sanitize_for_urwid(entry["date"])
            label = f"{icon} {name:<30} r{rev:<6} {author:<12} {date}"

            attr = "dir" if entry["kind"] == "dir" else "file"
            item = urwid.AttrMap(
                urwid.SelectableIcon(label, cursor_position=0),
                attr,
                focus_map="focus",
            )
            self.list_walker.append(item)

        if self.list_walker:
            self.list_walker.set_focus(0)
            self._on_focus_changed()

    def _set_preview_walker(self, widgets: list):
        """用给定的 widget 列表替换预览 ListBox 的内容，并滚动到顶部"""
        self.preview_walker[:] = widgets
        if widgets:
            self.preview_walker.set_focus(0)

    def _clear_preview(self):
        """清空右侧预览区域"""
        self.current_image_widget = None
        self._set_preview_walker([urwid.Text("")])
        self.preview_pile.contents[:] = [(self.preview_list_box, (urwid.WEIGHT, 1))]

    def _on_focus_changed(self):
        """当列表焦点变化时，取消旧定时器并安排防抖延迟加载预览"""
        focus_pos = self.list_walker.focus
        if focus_pos is None or focus_pos >= len(self.entries):
            return

        entry = self.entries[focus_pos]
        if entry["kind"] != "file":
            self._clear_preview()
            return

        # 立即显示占位提示，避免残留上一个文件的内容
        self._set_preview_walker([
            urwid.Text(("preview_title", f"⏳ 加载中: {entry['name']} ..."))
        ])
        self.preview_pile.contents[:] = [(self.preview_list_box, (urwid.WEIGHT, 1))]

        # 取消上一个未触发的定时器（防抖）
        if self._preview_alarm is not None:
            self.loop.remove_alarm(self._preview_alarm)
            self._preview_alarm = None

        target_url = f"{self.current_url}/{entry['name']}"
        filename = entry["name"]

        def _do_load(loop, user_data):
            self._preview_alarm = None
            if is_image_file(filename):
                self._preview_image(target_url, filename)
            elif is_binary_file(filename):
                ext = os.path.splitext(filename)[1].lower()
                self._set_preview_walker([
                    urwid.Text(("preview_title", f"📦 {filename}")),
                    urwid.Text(""),
                    urwid.Text(("error", f"  不支持预览 {ext} 格式的二进制文件")),
                ])
                self.preview_pile.contents[:] = [(self.preview_list_box, (urwid.WEIGHT, 1))]
            else:
                self._preview_text(target_url, filename)

        # 延迟 0.3 秒后再真正加载，快速 j/k 时只触发最后一次
        self._preview_alarm = self.loop.set_alarm_in(0.3, _do_load)

    def _markup_to_line_widgets(self, markup: list | str) -> list:
        """
        将 highlight_code 返回的 markup（或纯文本字符串）按行拆分，
        每行生成一个带行号的 Columns widget，供 ListBox 逐行渲染。

        行号列固定宽度，代码列使用 wrap="space" 避免 urwid clip 模式对
        零宽字符的 LayoutSegment sc=0 崩溃（ValueError: (0, 0, 1)）。
        """
        # 先收集所有行的内容（str 或 [(attr, text), ...] 列表）
        raw_lines = []

        if isinstance(markup, str):
            raw_lines = markup.splitlines() or [""]
        else:
            current_line: list = []
            for attr, text in markup:
                parts = text.split("\n")
                for index, part in enumerate(parts):
                    if part:
                        current_line.append((attr, part))
                    if index < len(parts) - 1:
                        raw_lines.append(current_line if current_line else "")
                        current_line = []
            raw_lines.append(current_line if current_line else "")

        if not raw_lines:
            raw_lines = [""]

        # 根据总行数决定行号列宽度（至少 3 位，如 "  1 "）
        total_lines = len(raw_lines)
        line_num_width = max(3, len(str(total_lines)))
        # 行号列总宽度 = 数字宽度 + 右侧分隔空格（" "）
        gutter_width = line_num_width + 1

        line_widgets = []
        for line_number, line_content in enumerate(raw_lines, start=1):
            line_num_str = str(line_number).rjust(line_num_width) + " "
            gutter = urwid.Text(("line_num", line_num_str), wrap="clip")
            code = urwid.Text(line_content, wrap="space")
            row = urwid.Columns(
                [("given", gutter_width, gutter), code],
                dividechars=0,
            )
            line_widgets.append(row)

        return line_widgets

    def _sanitize_text(self, text: str) -> str:
        """
        清理文本内容，移除会导致 urwid 渲染崩溃的字符。

        urwid 使用 wcwidth 库计算字符宽度，control_codes="ignore" 模式下
        \t 等控制字符宽度为 0，在 clip 模式下产生 sc=0 的 LayoutSegment 崩溃。
        """
        import unicodedata
        # 统一换行符，去掉 \r
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 将 \t 展开为 4 个空格，避免 wcwidth 对控制字符返回 0
        text = text.replace("\t", "    ")
        cleaned_chars = []
        for char in text:
            if char in ("\n", " "):
                cleaned_chars.append(char)
                continue
            category = unicodedata.category(char)
            # Cc = 控制字符（\x00-\x1f 等），wcwidth 返回 -1 或 0，丢弃
            if category == "Cc":
                continue
            # Cf = 格式字符（BOM、零宽空格、软连字符等），wcwidth 返回 0，丢弃
            if category == "Cf":
                continue
            # Mn = 非间距组合字符（音调符号等），wcwidth 返回 0，丢弃
            if category == "Mn":
                continue
            # Me = 封闭组合字符，wcwidth 返回 0，丢弃
            if category == "Me":
                continue
            cleaned_chars.append(char)
        return "".join(cleaned_chars)

    def _preview_text(self, url: str, filename: str):
        """预览文本文件，按行渲染到 ListBox 支持滚动"""
        self.current_image_widget = None
        content = svn_cat(url)
        content = self._sanitize_text(content)
        markup = highlight_code(content, filename)
        line_widgets = self._markup_to_line_widgets(markup)
        self._set_preview_walker(line_widgets)
        self.preview_pile.contents[:] = [(self.preview_list_box, (urwid.WEIGHT, 1))]

    def _preview_image(self, url: str, filename: str):
        """预览图片文件（使用 Kitty 协议）"""
        self._set_preview_walker([urwid.Text(f"🖼️  正在加载: {filename} ...")])

        image_data = svn_cat_binary(url)
        if image_data is None:
            self._set_preview_walker([urwid.Text(("error", f"[错误] 无法读取图片: {filename}"))])
            return

        kitty_image = load_kitty_image(image_data)
        if kitty_image is None:
            self._set_preview_walker([urwid.Text(("error", f"[错误] 无法解析图片: {filename}"))])
            return

        size_kb = len(image_data) / 1024
        title_widget = urwid.Text(
            ("preview_title", f"🖼️  {filename}  ({size_kb:.1f} KB)"),
            align="left",
        )

        # UrwidImage 会用 Kitty 协议渲染图片
        image_widget = UrwidImage(kitty_image, upscale=True)
        self.current_image_widget = image_widget

        # 图片预览：标题（PACK）+ 图片（WEIGHT），不用 ListBox
        self.preview_pile.contents[:] = [
            (title_widget, (urwid.PACK, None)),
            (image_widget, (urwid.WEIGHT, 1)),
        ]

    def handle_input(self, key: str | tuple) -> bool | None:
        """处理全局按键（key 为字符串，鼠标事件为 tuple，直接忽略）"""
        if isinstance(key, tuple):
            return None
        if key in ("q", "Q"):
            raise urwid.ExitMainLoop()

        if key in ("esc", "left", "h"):
            self._go_back()
            return

        if key in ("enter", "right", "l"):
            self._enter_item()
            return

        if key in ("j", "down"):
            self._move_cursor(1)
            return

        if key in ("k", "up"):
            self._move_cursor(-1)
            return

        if key in ("d", "page down"):
            self._scroll_preview(10)
            return

        if key in ("u", "page up"):
            self._scroll_preview(-10)
            return

    def _scroll_preview(self, lines: int):
        """滚动右侧预览区域，正数向下，负数向上"""
        current_focus = self.preview_walker.focus
        if current_focus is None:
            return
        new_focus = max(0, min(current_focus + lines, len(self.preview_walker) - 1))
        self.preview_walker.set_focus(new_focus)

    def _move_cursor(self, direction: int):
        """移动列表光标"""
        focus_pos = self.list_walker.focus
        if focus_pos is None:
            return
        new_pos = focus_pos + direction
        if 0 <= new_pos < len(self.list_walker):
            self.list_walker.set_focus(new_pos)
            self._on_focus_changed()

    def _enter_item(self):
        """进入目录或打开文件"""
        focus_pos = self.list_walker.focus
        if focus_pos is None or focus_pos >= len(self.entries):
            return

        entry = self.entries[focus_pos]
        if entry["kind"] == "dir":
            self.history.append(self.current_url)
            self.load_dir(f"{self.current_url}/{entry['name']}")

    def _go_back(self):
        """返回上级目录"""
        if self.history:
            prev_url = self.history.pop()
            self.load_dir(prev_url)


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: svn-viewer <svn_url>")
        print("Example: svn-viewer https://svn.apache.org/repos/asf/")
        sys.exit(1)

    url = sys.argv[1]
    browser = SvnBrowser(url)
    browser.run()


if __name__ == "__main__":
    main()
