# svn-viewer

A terminal UI browser for SVN repositories, with syntax highlighting and image preview (Kitty graphics protocol).

> GitHub: [https://github.com/hanxi/svn-viewer](https://github.com/hanxi/svn-viewer)

## Features

- 📂 Browse SVN repository directories interactively in the terminal
- 📄 Preview text files with syntax highlighting (powered by [Pygments](https://pygments.org/))
- 🖼️ Preview image files using the [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/) (requires a compatible terminal such as Kitty or Ghostty)
- ⌨️ Vim-style keyboard navigation (`j`/`k`, `h`/`l`, `esc`, `enter`)
- 🔍 Debounced preview loading to keep navigation snappy

## Requirements

- Python >= 3.14
- A terminal that supports the Kitty graphics protocol (e.g., [Kitty](https://sw.kovidgoyal.net/kitty/), [Ghostty](https://ghostty.org/))
- `svn` command-line client installed and available in `PATH`

## Installation

Install from PyPI:

```bash
pip install svn-viewer
```

Or clone and install locally for development:

```bash
git clone https://github.com/hanxi/svn-viewer.git
cd svn-viewer
pip install -e .
```

## Usage

Run directly without installing (via [uv](https://docs.astral.sh/uv/)):

```bash
uvx svn-viewer <svn_url>
```

Or if installed via pip:

```bash
svn-viewer <svn_url>
```

**Example:**

```bash
uvx svn-viewer https://svn.apache.org/repos/asf/
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `j` / `↓` | Move cursor down |
| `k` / `↑` | Move cursor up |
| `enter` / `→` / `l` | Enter directory |
| `esc` / `←` / `h` | Go back to parent directory |
| `d` / `Page Down` | Scroll preview down |
| `u` / `Page Up` | Scroll preview up |
| `q` | Quit |

## License

This project is licensed under the [MIT License](LICENSE).
