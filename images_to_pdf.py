from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

from PIL import Image, ImageOps


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_NAME_PATTERN = re.compile(r"^(?P<group>\d+_\d{2})-(?P<index>\d{8})$")
CONFIG_FILE = Path.home() / ".image_to_pdf_config.json"
MODE_SPLIT_BY_PREFIX = "split_by_prefix"
MODE_MERGE_ALL = "merge_all"
SUPPORTED_MODES = {MODE_SPLIT_BY_PREFIX, MODE_MERGE_ALL}
ProgressCallback = Callable[[int, int, str], None]


def is_supported_image(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
        and IMAGE_NAME_PATTERN.fullmatch(path.stem) is not None
    )


def get_image_group(path: Path) -> str:
    match = IMAGE_NAME_PATTERN.fullmatch(path.stem)
    if match is None:
        raise ValueError(f"Tên file không đúng định dạng: {path.name}")
    return match.group("group")


def load_app_config() -> dict[str, object]:
    if not CONFIG_FILE.exists():
        return {}

    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return config if isinstance(config, dict) else {}


def save_app_config(config: dict[str, object]) -> None:
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_last_input_dir() -> Path | None:
    config = load_app_config()

    input_dir = config.get("last_input_dir")
    if not input_dir:
        return None

    path = Path(input_dir).expanduser()
    return path if path.exists() and path.is_dir() else None


def save_last_input_dir(input_dir: Path) -> None:
    config = load_app_config()
    config["last_input_dir"] = str(input_dir.resolve())
    save_app_config(config)


def load_last_mode() -> str | None:
    config = load_app_config()
    mode = config.get("last_mode")
    return mode if mode in SUPPORTED_MODES else None


def save_last_mode(mode: str) -> None:
    if mode not in SUPPORTED_MODES:
        return

    config = load_app_config()
    config["last_mode"] = mode
    save_app_config(config)


def load_delete_after_use() -> bool:
    config = load_app_config()
    return bool(config.get("delete_after_use", False))


def save_delete_after_use(delete_after_use: bool) -> None:
    config = load_app_config()
    config["delete_after_use"] = delete_after_use
    save_app_config(config)


def load_last_output_name() -> str:
    config = load_app_config()
    output_name = config.get("last_output_name")
    return output_name if isinstance(output_name, str) else ""


def save_last_output_name(output_name: str) -> None:
    config = load_app_config()
    config["last_output_name"] = output_name
    save_app_config(config)


def load_last_output_dir() -> Path | None:
    config = load_app_config()

    output_dir = config.get("last_output_dir")
    if not output_dir:
        return None

    path = Path(output_dir).expanduser()
    return path if path.exists() and path.is_dir() else None


def save_last_output_dir(output_dir: Path) -> None:
    config = load_app_config()
    config["last_output_dir"] = str(output_dir.resolve())
    save_app_config(config)


def choose_input_dir(parent: object, initial_dir: Path | None) -> Path | None:
    selected_dir = filedialog.askdirectory(
        parent=parent,
        title="Chọn thư mục chứa ảnh",
        initialdir=str(initial_dir) if initial_dir else str(Path.cwd()),
    )

    if not selected_dir:
        return None

    return Path(selected_dir)


def choose_output_dir(parent: object, initial_dir: Path | None) -> Path | None:
    selected_dir = filedialog.askdirectory(
        parent=parent,
        title="Chọn thư mục output",
        initialdir=str(initial_dir) if initial_dir else str(Path.cwd()),
    )

    if not selected_dir:
        return None

    return Path(selected_dir)


def load_image_paths(input_dir: Path) -> list[Path]:
    image_paths = sorted(path for path in input_dir.iterdir() if is_supported_image(path))
    if not image_paths:
        raise FileNotFoundError(
            "Không tìm thấy ảnh hợp lệ trong thư mục: "
            f"{input_dir}\nTên file phải có dạng timestamp_xx-xxxxxxxx"
        )

    return image_paths


def load_image_groups(input_dir: Path) -> dict[str, list[Path]]:
    image_paths = load_image_paths(input_dir)

    groups: dict[str, list[Path]] = {}
    for image_path in image_paths:
        group_name = get_image_group(image_path)
        groups.setdefault(group_name, []).append(image_path)

    return groups


def summarize_input_dir(input_dir: Path, mode: str) -> str:
    image_paths = load_image_paths(input_dir)
    group_count = len({get_image_group(path) for path in image_paths})
    mode_text = (
        "Gộp tất cả ảnh thành 1 PDF"
        if mode == MODE_MERGE_ALL
        else "Tách nhiều PDF theo tiền tố"
    )
    return (
        f"Đã chọn thư mục:\n{input_dir}\n\n"
        f"Số ảnh hợp lệ tìm được: {len(image_paths)}\n"
        f"Số nhóm theo tiền tố: {group_count}\n"
        f"Chế độ hiện tại: {mode_text}\n\n"
        "Nhấn “Tạo PDF” để bắt đầu."
    )


def sanitize_output_name(output_name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", output_name).strip(" ._")
    return sanitized


def build_output_name_preview(custom_output_name: str, mode: str) -> str:
    sanitized_name = sanitize_output_name(custom_output_name)
    if sanitized_name:
        if mode == MODE_MERGE_ALL:
            return f"Tên file output: {sanitized_name}_yyyy-mm-dd_hh-mm-ss_<số_trang>.pdf"
        return f"Tên file output (ví dụ): {sanitized_name}_yyyy-mm-dd_hh-mm-ss_<số_trang>.pdf"

    if mode == MODE_MERGE_ALL:
        return "Tên file output: <tên_thư_mục> (<số_ảnh>).pdf"

    return "Tên file output (ví dụ): <timestamp_xx> (<số_ảnh>).pdf"


def load_pdf_pages(
    image_paths: list[Path],
    progress_callback: ProgressCallback | None = None,
    progress_state: dict[str, int] | None = None,
) -> list[Image.Image]:
    if not image_paths:
        raise FileNotFoundError("Không có ảnh để tạo PDF.")

    pages: list[Image.Image] = []
    for image_path in image_paths:
        with Image.open(image_path) as img:
            normalized = ImageOps.exif_transpose(img)

            if normalized.width > normalized.height:
                normalized = normalized.rotate(90, expand=True)

            if normalized.mode != "RGB":
                normalized = normalized.convert("RGB")
            else:
                normalized = normalized.copy()

            pages.append(normalized)
            if progress_callback is not None and progress_state is not None:
                progress_state["current"] += 1
                progress_callback(
                    progress_state["current"],
                    progress_state["total"],
                    f"Đang xử lý ảnh: {image_path.name}",
                )

    return pages


def save_pdf(
    image_paths: list[Path],
    output_file: Path,
    progress_callback: ProgressCallback | None = None,
    progress_state: dict[str, int] | None = None,
) -> None:
    pages = load_pdf_pages(
        image_paths,
        progress_callback=progress_callback,
        progress_state=progress_state,
    )
    first_page, rest_pages = pages[0], pages[1:]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    first_page.save(output_file, save_all=True, append_images=rest_pages)

    for page in pages:
        page.close()


def resolve_output_file(output_path: Path, group_name: str, image_count: int) -> Path:
    output_dir = output_path.parent if output_path.suffix.lower() == ".pdf" else output_path
    return output_dir / f"{group_name} ({image_count}).pdf"


def resolve_output_dir(output_path: Path) -> Path:
    return output_path.parent if output_path.suffix.lower() == ".pdf" else output_path


def ensure_unique_output_file(path: Path, used_names: set[str]) -> Path:
    candidate = path
    suffix = 2
    while candidate.name in used_names or candidate.exists():
        candidate = path.with_name(f"{path.stem}_{suffix}{path.suffix}")
        suffix += 1
    used_names.add(candidate.name)
    return candidate


def resolve_custom_output_file(
    output_path: Path,
    output_name: str,
    image_count: int,
    timestamp_text: str,
    used_names: set[str],
) -> Path:
    output_dir = resolve_output_dir(output_path)
    base_name = sanitize_output_name(output_name)
    if not base_name:
        raise ValueError("Tên file output không hợp lệ.")

    candidate = output_dir / f"{base_name}_{timestamp_text}_{image_count}.pdf"
    return ensure_unique_output_file(candidate, used_names)


def resolve_merged_output_file(output_path: Path, input_dir: Path, image_count: int) -> Path:
    if output_path.suffix.lower() == ".pdf":
        return output_path.with_name(f"{output_path.stem} ({image_count}).pdf")

    base_name = input_dir.name.strip() or "merged_images"
    return output_path / f"{base_name} ({image_count}).pdf"


def delete_images(
    image_paths: list[Path],
    progress_callback: ProgressCallback | None = None,
    progress_state: dict[str, int] | None = None,
) -> int:
    deleted_count = 0
    for image_path in image_paths:
        image_path.unlink()
        deleted_count += 1
        if progress_callback is not None and progress_state is not None:
            progress_state["current"] += 1
            progress_callback(
                progress_state["current"],
                progress_state["total"],
                f"Đang xóa ảnh: {image_path.name}",
            )
    return deleted_count


def verify_output_files(output_files: list[tuple[Path, int]]) -> None:
    missing_files = [output_file for output_file, _ in output_files if not output_file.exists()]
    if missing_files:
        missing_list = "\n".join(str(path) for path in missing_files)
        raise FileNotFoundError(
            "Chưa thể xóa ảnh vì một số file PDF chưa được tạo thành công:\n"
            f"{missing_list}"
        )

    empty_files = [output_file for output_file, _ in output_files if output_file.stat().st_size == 0]
    if empty_files:
        empty_list = "\n".join(str(path) for path in empty_files)
        raise OSError(
            "Chưa thể xóa ảnh vì một số file PDF đang rỗng:\n"
            f"{empty_list}"
        )


def build_pdfs(
    input_dir: Path,
    output_path: Path,
    mode: str = MODE_SPLIT_BY_PREFIX,
    delete_after_use: bool = False,
    progress_callback: ProgressCallback | None = None,
    custom_output_name: str = "",
) -> list[tuple[Path, int]]:
    processed_image_paths: list[Path] = []
    timestamp_text = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    used_names: set[str] = set()

    if mode == MODE_MERGE_ALL:
        image_paths = load_image_paths(input_dir)
        total_steps = len(image_paths) + (len(image_paths) if delete_after_use else 0)
        progress_state = {"current": 0, "total": max(total_steps, 1)}
        if progress_callback is not None:
            progress_callback(0, progress_state["total"], "Bắt đầu tạo PDF...")
        output_file = (
            resolve_custom_output_file(
                output_path,
                custom_output_name,
                len(image_paths),
                timestamp_text,
                used_names,
            )
            if custom_output_name.strip()
            else resolve_merged_output_file(output_path, input_dir, len(image_paths))
        )
        save_pdf(
            image_paths,
            output_file,
            progress_callback=progress_callback,
            progress_state=progress_state,
        )
        processed_image_paths.extend(image_paths)
        output_files = [(output_file, len(image_paths))]
        if delete_after_use:
            verify_output_files(output_files)
            delete_images(
                processed_image_paths,
                progress_callback=progress_callback,
                progress_state=progress_state,
            )
        if progress_callback is not None:
            progress_callback(
                progress_state["total"],
                progress_state["total"],
                "Hoàn tất tạo PDF.",
            )
        return output_files

    if mode != MODE_SPLIT_BY_PREFIX:
        raise ValueError(f"Chế độ không hợp lệ: {mode}")

    image_groups = load_image_groups(input_dir)
    total_images = sum(len(paths) for paths in image_groups.values())
    total_steps = total_images + (total_images if delete_after_use else 0)
    progress_state = {"current": 0, "total": max(total_steps, 1)}
    if progress_callback is not None:
        progress_callback(0, progress_state["total"], "Bắt đầu tạo PDF...")
    output_files: list[tuple[Path, int]] = []

    for group_name, image_paths in image_groups.items():
        output_file = (
            resolve_custom_output_file(
                output_path,
                custom_output_name,
                len(image_paths),
                timestamp_text,
                used_names,
            )
            if custom_output_name.strip()
            else resolve_output_file(output_path, group_name, len(image_paths))
        )
        save_pdf(
            image_paths,
            output_file,
            progress_callback=progress_callback,
            progress_state=progress_state,
        )
        processed_image_paths.extend(image_paths)
        output_files.append((output_file, len(image_paths)))

    if delete_after_use:
        verify_output_files(output_files)
        delete_images(
            processed_image_paths,
            progress_callback=progress_callback,
            progress_state=progress_state,
        )

    if progress_callback is not None:
        progress_callback(
            progress_state["total"],
            progress_state["total"],
            "Hoàn tất tạo PDF.",
        )

    return output_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Xoay ảnh ngang thành dọc và xuất PDF theo một hoặc nhiều nhóm ảnh."
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        help="Thư mục chứa ảnh. Nếu bỏ trống, ứng dụng sẽ dùng thư mục đã nhớ hoặc chờ bạn chọn.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output.pdf"),
        help="Thư mục hoặc file mẫu đầu ra. PDF sẽ được đặt tên theo dạng timestamp_xx.pdf.",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=sorted(SUPPORTED_MODES),
        help="Chế độ xuất PDF: gộp tất cả thành một file hoặc tách theo tiền tố.",
    )
    parser.add_argument(
        "--delete-after-use",
        action="store_true",
        help="Xóa ảnh nguồn sau khi tạo PDF thành công.",
    )
    parser.add_argument(
        "--output-name",
        default="",
        help="Tên file output tùy chỉnh. Nếu có giá trị, tên file sẽ theo dạng ten_file_yyyy-mm-dd_hh-mm-ss_so_trang.pdf.",
    )
    return parser.parse_args()


def resolve_initial_input_dir(input_dir: Path | None) -> Path | None:
    if input_dir is not None:
        resolved_input_dir = input_dir.expanduser()
    else:
        resolved_input_dir = load_last_input_dir()

    if resolved_input_dir is None:
        return None

    if not resolved_input_dir.exists() or not resolved_input_dir.is_dir():
        raise FileNotFoundError(f"Thư mục không tồn tại: {resolved_input_dir}")

    return resolved_input_dir


def resolve_initial_mode(mode: str | None) -> str:
    if mode in SUPPORTED_MODES:
        return mode

    saved_mode = load_last_mode()
    if saved_mode is not None:
        return saved_mode

    return MODE_SPLIT_BY_PREFIX


def resolve_initial_delete_after_use(delete_after_use: bool) -> bool:
    if delete_after_use:
        return True
    return load_delete_after_use()


def resolve_initial_output_name(output_name: str) -> str:
    return output_name if output_name else load_last_output_name()


def resolve_initial_output_dir(output_path: Path) -> Path:
    saved_output_dir = load_last_output_dir()
    if saved_output_dir is not None:
        return saved_output_dir
    return resolve_output_dir(output_path).expanduser().resolve()


def main() -> None:
    args = parse_args()
    startup_error: str | None = None
    initial_mode = resolve_initial_mode(args.mode)
    initial_delete_after_use = resolve_initial_delete_after_use(args.delete_after_use)
    initial_output_name = resolve_initial_output_name(args.output_name)
    initial_output_dir = resolve_initial_output_dir(args.output)

    try:
        initial_input_dir = resolve_initial_input_dir(args.input_dir)
    except Exception as exc:
        initial_input_dir = None
        startup_error = str(exc)

    root = tk.Tk()
    root.title("💕 Tạo PDF từ ảnh cho Emmm IUUU 💕")
    root.geometry("1000x780")
    root.minsize(940, 700)
    root.configure(bg="#f6f8fb")

    style = ttk.Style()
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("App.TFrame", background="#f6f8fb")
    style.configure(
        "Card.TFrame",
        background="#ffffff",
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "Title.TLabel",
        background="#f6f8fb",
        foreground="#0f172a",
        font=("Arial", 22, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        background="#f6f8fb",
        foreground="#475569",
        font=("Arial", 10),
    )
    style.configure(
        "Section.TLabel",
        background="#ffffff",
        foreground="#0f172a",
        font=("Arial", 11, "bold"),
    )
    style.configure(
        "Body.TLabel",
        background="#ffffff",
        foreground="#475569",
        font=("Arial", 10),
    )
    style.configure(
        "Status.TLabel",
        background="#ffffff",
        foreground="#0f172a",
        font=("Arial", 10, "bold"),
    )
    style.configure(
        "Primary.TButton",
        font=("Arial", 10, "bold"),
        padding=(16, 10),
        background="#2563eb",
        foreground="#ffffff",
        borderwidth=0,
        focusthickness=0,
        relief="flat",
    )
    style.map(
        "Primary.TButton",
        background=[("active", "#1d4ed8"), ("pressed", "#1e40af")],
        foreground=[("disabled", "#cbd5e1")],
    )
    style.configure(
        "Secondary.TButton",
        font=("Arial", 10),
        padding=(14, 10),
        background="#eef2ff",
        foreground="#1e3a8a",
        borderwidth=0,
        focusthickness=0,
        relief="flat",
    )
    style.map(
        "Secondary.TButton",
        background=[("active", "#dbeafe"), ("pressed", "#bfdbfe")],
        foreground=[("disabled", "#94a3b8")],
    )
    style.configure(
        "Modern.TEntry",
        fieldbackground="#ffffff",
        foreground="#0f172a",
        bordercolor="#e2e8f0",
        lightcolor="#e2e8f0",
        darkcolor="#e2e8f0",
        padding=(10, 8),
        insertcolor="#0f172a",
    )
    style.map(
        "Modern.TEntry",
        bordercolor=[("focus", "#93c5fd")],
        lightcolor=[("focus", "#93c5fd")],
        darkcolor=[("focus", "#93c5fd")],
    )
    style.configure(
        "Modern.TRadiobutton",
        background="#ffffff",
        foreground="#0f172a",
        font=("Arial", 10),
    )
    style.configure(
        "Modern.TCheckbutton",
        background="#ffffff",
        foreground="#0f172a",
        font=("Arial", 10),
    )

    frame = ttk.Frame(root, padding=20, style="App.TFrame")
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=3)
    frame.columnconfigure(1, weight=2)
    frame.rowconfigure(3, weight=1)

    ttk.Label(
        frame,
        text="💕 Tạo PDF từ ảnh cho Emmm IUUU 💕",
        style="Title.TLabel",
    ).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(
        frame,
        text=(
            "Chỉ xử lý các ảnh có tên dạng timestamp_xx-xxxxxxxx.* "
            "và có thể xuất thành một PDF duy nhất hoặc nhiều PDF theo tiền tố timestamp_xx."
        ),
        style="Subtitle.TLabel",
        wraplength=920,
        justify="left",
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 18))

    source_card = ttk.Frame(frame, padding=22, style="Card.TFrame")
    source_card.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
    source_card.columnconfigure(0, weight=1)

    options_card = ttk.Frame(frame, padding=22, style="Card.TFrame")
    options_card.grid(row=2, column=1, sticky="nsew", padx=(10, 0))
    options_card.columnconfigure(0, weight=1)

    ttk.Label(source_card, text="Nguồn dữ liệu", style="Section.TLabel").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(
        source_card,
        text="Chọn thư mục ảnh, đặt tên file nếu cần. Ứng dụng sẽ nhớ các lựa chọn gần nhất.",
        style="Body.TLabel",
        wraplength=520,
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(4, 14))

    selected_dir_var = tk.StringVar(value=str(initial_input_dir) if initial_input_dir else "")
    output_dir_var = tk.StringVar(value=str(initial_output_dir))
    output_name_var = tk.StringVar(value=initial_output_name)
    mode_var = tk.StringVar(value=initial_mode)
    delete_after_use_var = tk.BooleanVar(value=initial_delete_after_use)
    status_var = tk.StringVar(value="Sẵn sàng.")
    progress_text_var = tk.StringVar(value="Chưa bắt đầu xử lý.")
    output_file_preview_var = tk.StringVar(
        value=build_output_name_preview(initial_output_name, initial_mode)
    )
    worker_queue: Queue[tuple[str, object]] = Queue()
    is_processing = False

    ttk.Label(source_card, text="Thư mục ảnh", style="Section.TLabel").grid(
        row=2, column=0, sticky="w"
    )
    dir_row = ttk.Frame(source_card, style="Card.TFrame")
    dir_row.grid(row=3, column=0, sticky="ew", pady=(6, 12))
    dir_row.columnconfigure(0, weight=1)

    dir_entry = ttk.Entry(dir_row, textvariable=selected_dir_var, font=("Arial", 10), style="Modern.TEntry")
    dir_entry.grid(row=0, column=0, sticky="ew")
    choose_dir_button = ttk.Button(
        dir_row,
        text="Chọn thư mục",
        style="Secondary.TButton",
        command=lambda: on_choose_dir(),
    )
    choose_dir_button.grid(row=0, column=1, padx=(12, 0))
    ttk.Label(
        dir_row,
        text="Ứng dụng sẽ nhớ thư mục bạn chọn gần nhất.",
        style="Body.TLabel",
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

    ttk.Label(source_card, text="Thư mục output", style="Section.TLabel").grid(
        row=4, column=0, sticky="w"
    )
    output_row = ttk.Frame(source_card, style="Card.TFrame")
    output_row.grid(row=5, column=0, sticky="ew", pady=(6, 12))
    output_row.columnconfigure(0, weight=1)
    output_entry = ttk.Entry(
        output_row,
        textvariable=output_dir_var,
        font=("Arial", 10),
        style="Modern.TEntry",
    )
    output_entry.grid(row=0, column=0, sticky="ew")
    choose_output_button = ttk.Button(
        output_row,
        text="Chọn thư mục",
        style="Secondary.TButton",
        command=lambda: on_choose_output_dir(),
    )
    choose_output_button.grid(row=0, column=1, padx=(12, 0))
    open_output_button = ttk.Button(
        output_row,
        text="Mở thư mục",
        style="Secondary.TButton",
        command=lambda: on_open_output_dir(),
    )
    open_output_button.grid(row=0, column=2, padx=(12, 0))
    ttk.Label(
        output_row,
        textvariable=output_file_preview_var,
        style="Body.TLabel",
        wraplength=520,
        justify="left",
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    ttk.Label(source_card, text="Tên file output", style="Section.TLabel").grid(
        row=6, column=0, sticky="w"
    )
    output_name_frame = ttk.Frame(source_card, style="Card.TFrame")
    output_name_frame.grid(row=7, column=0, sticky="ew")
    output_name_frame.columnconfigure(0, weight=1)
    output_name_entry = ttk.Entry(
        output_name_frame,
        textvariable=output_name_var,
        font=("Arial", 10),
        style="Modern.TEntry",
    )
    output_name_entry.grid(row=0, column=0, sticky="ew")
    ttk.Label(
        output_name_frame,
        text=(
            "Để trống để giữ cấu trúc tên hiện tại. Nếu nhập tên, file sẽ có dạng "
            "tên_file_yyyy-mm-dd_hh-mm-ss_số_trang.pdf."
        ),
        style="Body.TLabel",
        wraplength=520,
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Label(options_card, text="Tùy chọn xuất", style="Section.TLabel").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(
        options_card,
        text="Chọn cách gộp PDF, tùy chọn xóa ảnh và theo dõi tiến độ xử lý.",
        style="Body.TLabel",
        wraplength=320,
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(4, 14))

    ttk.Label(options_card, text="Chế độ xuất", style="Section.TLabel").grid(
        row=2, column=0, sticky="w"
    )
    mode_row = ttk.Frame(options_card, style="Card.TFrame")
    mode_row.grid(row=3, column=0, sticky="w", pady=(6, 12))

    merge_mode_radio = ttk.Radiobutton(
        mode_row,
        text="Gộp tất cả ảnh thành 1 PDF",
        value=MODE_MERGE_ALL,
        variable=mode_var,
        style="Modern.TRadiobutton",
    )
    merge_mode_radio.pack(side="left")
    split_mode_radio = ttk.Radiobutton(
        mode_row,
        text="Tách nhiều PDF theo tiền tố",
        value=MODE_SPLIT_BY_PREFIX,
        variable=mode_var,
        style="Modern.TRadiobutton",
    )
    split_mode_radio.pack(side="left", padx=(18, 0))

    ttk.Label(options_card, text="Tùy chọn khác", style="Section.TLabel").grid(
        row=4, column=0, sticky="w"
    )
    delete_after_use_checkbox = ttk.Checkbutton(
        options_card,
        text="Xóa ảnh sau khi tạo PDF thành công",
        variable=delete_after_use_var,
        style="Modern.TCheckbutton",
    )
    delete_after_use_checkbox.grid(row=5, column=0, sticky="w", pady=(6, 12))

    ttk.Label(options_card, text="Thao tác", style="Section.TLabel").grid(
        row=6, column=0, sticky="w"
    )
    button_row = ttk.Frame(options_card, style="Card.TFrame")
    button_row.grid(row=7, column=0, sticky="ew", pady=(6, 0))
    status_panel = ttk.Frame(options_card, style="Card.TFrame")
    status_panel.grid(row=8, column=0, sticky="ew", pady=(14, 0))

    results_card = ttk.Frame(frame, padding=22, style="Card.TFrame")
    results_card.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(16, 0))
    results_card.rowconfigure(3, weight=1)
    results_card.grid_rowconfigure(3, minsize=220)
    results_card.columnconfigure(0, weight=1)

    ttk.Label(results_card, text="Kết quả", style="Section.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(
        results_card,
        text="Thông báo xử lý, lỗi và danh sách file PDF sẽ hiển thị tại đây.",
        style="Body.TLabel",
        wraplength=780,
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(4, 10))

    progress_row = ttk.Frame(results_card, style="Card.TFrame")
    progress_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
    progress_header = ttk.Frame(progress_row, style="Card.TFrame")
    progress_header.pack(fill="x")
    ttk.Label(progress_header, text="Tiến độ", style="Section.TLabel").pack(side="left")
    progress_percent_var = tk.StringVar(value="0%")
    ttk.Label(progress_header, textvariable=progress_percent_var, style="Status.TLabel").pack(
        side="right"
    )
    progress_visual_state = {"ratio": 0.0}
    progress_bar = tk.Canvas(
        progress_row,
        height=22,
        bg="#e2e8f0",
        highlightthickness=0,
        bd=0,
    )
    progress_bar.pack(fill="x", pady=(8, 0))
    progress_bar.create_rectangle(0, 0, 1, 22, outline="", fill="#e2e8f0", tags="track")
    progress_bar.create_rectangle(0, 0, 0, 22, outline="", fill="#2f80ed", tags="fill")
    ttk.Label(
        progress_row,
        textvariable=progress_text_var,
        style="Body.TLabel",
        wraplength=780,
        justify="left",
    ).pack(anchor="w", pady=(6, 0))

    result_box = scrolledtext.ScrolledText(
        results_card,
        wrap="word",
        font=("Arial", 10),
        height=12,
        padx=10,
        pady=10,
        relief="flat",
        bd=0,
        highlightthickness=0,
        background="#f8fafc",
        foreground="#0f172a",
        insertbackground="#0f172a",
    )
    result_box.grid(row=3, column=0, sticky="nsew", pady=(14, 0))
    result_box.configure(state="disabled")

    ttk.Label(status_panel, text="Trạng thái", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        status_panel,
        textvariable=status_var,
        style="Status.TLabel",
        wraplength=320,
        justify="left",
    ).pack(anchor="w", pady=(6, 0))

    def set_controls_enabled(enabled: bool) -> None:
        state = "!disabled" if enabled else "disabled"
        for widget in (
            dir_entry,
            choose_dir_button,
            output_entry,
            choose_output_button,
            open_output_button,
            merge_mode_radio,
            split_mode_radio,
            delete_after_use_checkbox,
            output_name_entry,
            create_button,
        ):
            widget.state([state] if enabled else ["disabled"])

    def refresh_output_name_preview() -> None:
        output_file_preview_var.set(
            build_output_name_preview(output_name_var.get().strip(), mode_var.get())
        )

    def render_progress_bar(ratio: float) -> None:
        bounded_ratio = max(0.0, min(ratio, 1.0))
        progress_visual_state["ratio"] = bounded_ratio
        progress_bar.update_idletasks()
        width = max(progress_bar.winfo_width(), 1)
        height = max(progress_bar.winfo_height(), 22)
        progress_bar.coords("track", 0, 0, width, height)
        progress_bar.coords("fill", 0, 0, int(width * bounded_ratio), height)

    def on_progress_resize(_: object) -> None:
        render_progress_bar(progress_visual_state["ratio"])

    progress_bar.bind("<Configure>", on_progress_resize)

    def start_progress(message: str) -> None:
        render_progress_bar(0.08)
        progress_percent_var.set("...")
        progress_text_var.set(message)

    def update_progress(current: int, total: int, message: str) -> None:
        total_value = max(total, 1)
        current_value = min(current, total_value)
        render_progress_bar(current_value / total_value)
        progress_percent_var.set(f"{int((current_value / total_value) * 100)}%")
        progress_text_var.set(f"{message} ({current_value}/{total_value})")

    def finish_progress(message: str, *, is_error: bool = False) -> None:
        if is_error:
            render_progress_bar(0.0)
            progress_percent_var.set("0%")
        else:
            render_progress_bar(1.0)
            progress_percent_var.set("100%")
        progress_text_var.set(message)

    def handle_build_success(
        input_dir: Path,
        output_dir: Path,
        selected_mode: str,
        delete_after_use: bool,
        output_files: list[tuple[Path, int]],
    ) -> None:
        total_files = len(output_files)
        total_images = sum(image_count for _, image_count in output_files)
        mode_text = (
            "Gộp tất cả ảnh thành 1 PDF"
            if selected_mode == MODE_MERGE_ALL
            else "Tách nhiều PDF theo tiền tố"
        )
        delete_text = "Có" if delete_after_use else "Không"
        deleted_summary = f"Số ảnh đã xóa: {total_images}\n\n" if delete_after_use else ""
        details = "\n".join(
            f"- {output_file.name}: {image_count} ảnh\n  {output_file}"
            for output_file, image_count in output_files
        )
        set_result(
            f"Tạo PDF thành công.\n\n"
            f"Thư mục nguồn: {input_dir}\n"
            f"Thư mục output: {output_dir}\n"
            f"Chế độ xuất: {mode_text}\n"
            f"Xóa ảnh sau khi tạo PDF: {delete_text}\n"
            f"Số file PDF đã tạo: {total_files}\n"
            f"Tổng số ảnh đã xử lý: {total_images}\n\n"
            f"{deleted_summary}"
            f"Chi tiết:\n{details}"
        )

    def poll_worker_queue() -> None:
        nonlocal is_processing
        should_continue_polling = is_processing

        while True:
            try:
                event_type, payload = worker_queue.get_nowait()
            except Empty:
                break

            if event_type == "progress":
                current, total, message = payload
                update_progress(current, total, message)
            elif event_type == "success":
                input_dir, output_dir, selected_mode, delete_after_use, output_files = payload
                finish_progress("Hoàn tất xử lý.")
                handle_build_success(
                    input_dir,
                    output_dir,
                    selected_mode,
                    delete_after_use,
                    output_files,
                )
                set_controls_enabled(True)
                is_processing = False
                should_continue_polling = False
            elif event_type == "error":
                finish_progress("Xử lý thất bại.", is_error=True)
                set_result(str(payload), is_error=True)
                set_controls_enabled(True)
                is_processing = False
                should_continue_polling = False

        if should_continue_polling:
            root.after(50, poll_worker_queue)

    def set_result(
        message: str, *, is_error: bool = False, status_message: str | None = None
    ) -> None:
        result_box.configure(state="normal")
        result_box.delete("1.0", tk.END)
        result_box.insert("1.0", message)
        result_box.configure(
            state="disabled",
            foreground="#8a1c1c" if is_error else "#243b53",
        )
        if status_message is not None:
            status_var.set(status_message)
        else:
            status_var.set("Có lỗi xảy ra." if is_error else "Đã hoàn thành.")

    def on_choose_dir() -> None:
        current_dir = Path(selected_dir_var.get()).expanduser() if selected_dir_var.get() else None
        selected_dir = choose_input_dir(root, current_dir or load_last_input_dir())
        if selected_dir is None:
            return

        selected_dir_var.set(str(selected_dir))
        save_last_input_dir(selected_dir)
        try:
            set_result(
                summarize_input_dir(selected_dir, mode_var.get()),
                status_message="Đã cập nhật thư mục ảnh.",
            )
        except Exception as exc:
            set_result(str(exc), is_error=True, status_message="Có lỗi xảy ra.")

    def on_open_output_dir() -> None:
        raw_output_dir = output_dir_var.get().strip()
        if not raw_output_dir:
            set_result(
                "Bạn chưa chọn thư mục output.\nHãy chọn thư mục output để tiếp tục.",
                is_error=True,
            )
            return

        output_dir = Path(raw_output_dir).expanduser().resolve()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["open", str(output_dir)])
            save_last_output_dir(output_dir)
            status_var.set("Đã mở thư mục output.")
        except Exception as exc:
            set_result(f"Không thể mở thư mục output:\n{exc}", is_error=True)

    def on_choose_output_dir() -> None:
        current_dir = Path(output_dir_var.get()).expanduser() if output_dir_var.get() else None
        selected_output_dir = choose_output_dir(root, current_dir or load_last_output_dir())
        if selected_output_dir is None:
            return

        resolved_output_dir = selected_output_dir.resolve()
        output_dir_var.set(str(resolved_output_dir))
        save_last_output_dir(resolved_output_dir)
        status_var.set("Đã cập nhật thư mục output.")

    def on_build_pdfs() -> None:
        nonlocal is_processing
        raw_dir = selected_dir_var.get().strip()
        raw_output_dir = output_dir_var.get().strip()
        custom_output_name = output_name_var.get().strip()
        selected_mode = mode_var.get()
        delete_after_use = delete_after_use_var.get()
        if is_processing:
            return
        if not raw_dir:
            set_result("Bạn chưa chọn thư mục ảnh.\nHãy bấm “Chọn thư mục” để tiếp tục.", is_error=True)
            return
        if not raw_output_dir:
            set_result(
                "Bạn chưa chọn thư mục output.\nHãy bấm “Chọn thư mục” ở phần output để tiếp tục.",
                is_error=True,
            )
            return

        input_dir = Path(raw_dir).expanduser()
        if not input_dir.exists() or not input_dir.is_dir():
            set_result(f"Thư mục không tồn tại:\n{input_dir}", is_error=True)
            return

        output_dir = Path(raw_output_dir).expanduser()
        output_path = output_dir.resolve()

        status_var.set("Đang tạo PDF...")
        start_progress("Đang chuẩn bị xử lý...")
        set_controls_enabled(False)
        is_processing = True
        save_last_input_dir(input_dir)
        save_last_output_dir(output_path)
        save_last_mode(selected_mode)
        save_delete_after_use(delete_after_use)
        save_last_output_name(custom_output_name)

        def queue_progress(current: int, total: int, message: str) -> None:
            worker_queue.put(("progress", (current, total, message)))

        def run_build() -> None:
            try:
                output_files = build_pdfs(
                    input_dir,
                    output_path,
                    selected_mode,
                    delete_after_use=delete_after_use,
                    progress_callback=queue_progress,
                    custom_output_name=custom_output_name,
                )
                worker_queue.put(
                    ("success", (input_dir, output_path, selected_mode, delete_after_use, output_files))
                )
            except Exception as exc:
                worker_queue.put(("error", exc))

        threading.Thread(target=run_build, daemon=True).start()
        root.after(20, poll_worker_queue)

    output_name_var.trace_add("write", lambda *_: refresh_output_name_preview())
    mode_var.trace_add("write", lambda *_: refresh_output_name_preview())

    create_button = ttk.Button(
        button_row,
        text="Tạo PDF",
        style="Primary.TButton",
        command=on_build_pdfs,
    )
    create_button.pack(side="left")
    ttk.Button(
        button_row,
        text="Đóng",
        style="Secondary.TButton",
        command=root.destroy,
    ).pack(side="right")

    if initial_input_dir is not None:
        try:
            set_result(
                summarize_input_dir(initial_input_dir, initial_mode)
                + f"\nXóa ảnh sau khi tạo PDF: {'Có' if initial_delete_after_use else 'Không'}"
                + (
                    f"\nTên file output tùy chỉnh: {initial_output_name}"
                    if initial_output_name
                    else ""
                ),
                status_message="Sẵn sàng.",
            )
        except Exception as exc:
            set_result(str(exc), is_error=True, status_message="Có lỗi xảy ra.")
    else:
        set_result(
            "Chào bạn.\n\nHãy chọn thư mục chứa ảnh, chọn chế độ xuất rồi nhấn “Tạo PDF”.",
            status_message="Sẵn sàng.",
        )

    finish_progress("Chưa bắt đầu xử lý.", is_error=True)

    if startup_error:
        set_result(startup_error, is_error=True)

    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    target_width = min(max(root.winfo_reqwidth() + 24, 1000), screen_width - 80)
    target_height = min(max(root.winfo_reqheight() + 24, 780), screen_height - 100)
    x_position = max((screen_width - target_width) // 2, 0)
    y_position = max((screen_height - target_height) // 2, 0)
    root.geometry(f"{target_width}x{target_height}+{x_position}+{y_position}")

    output_name_entry.focus_set()

    root.mainloop()


if __name__ == "__main__":
    main()
