from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path

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


def choose_input_dir(parent: object, initial_dir: Path | None) -> Path | None:
    from tkinter import filedialog

    selected_dir = filedialog.askdirectory(
        parent=parent,
        title="Chọn thư mục chứa ảnh",
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


def resolve_output_file(output_path: Path, group_name: str) -> Path:
    output_dir = output_path.parent if output_path.suffix.lower() == ".pdf" else output_path
    return output_dir / f"{group_name}.pdf"


def resolve_output_dir(output_path: Path) -> Path:
    return output_path.parent if output_path.suffix.lower() == ".pdf" else output_path


def resolve_merged_output_file(output_path: Path, input_dir: Path) -> Path:
    if output_path.suffix.lower() == ".pdf":
        return output_path

    base_name = input_dir.name.strip() or "merged_images"
    return output_path / f"{base_name}.pdf"


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


def build_pdfs(
    input_dir: Path,
    output_path: Path,
    mode: str = MODE_SPLIT_BY_PREFIX,
    delete_after_use: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> list[tuple[Path, int]]:
    processed_image_paths: list[Path] = []

    if mode == MODE_MERGE_ALL:
        image_paths = load_image_paths(input_dir)
        total_steps = len(image_paths) + (len(image_paths) if delete_after_use else 0)
        progress_state = {"current": 0, "total": max(total_steps, 1)}
        if progress_callback is not None:
            progress_callback(0, progress_state["total"], "Bắt đầu tạo PDF...")
        output_file = resolve_merged_output_file(output_path, input_dir)
        save_pdf(
            image_paths,
            output_file,
            progress_callback=progress_callback,
            progress_state=progress_state,
        )
        processed_image_paths.extend(image_paths)
        output_files = [(output_file, len(image_paths))]
        if delete_after_use:
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
        output_file = resolve_output_file(output_path, group_name)
        save_pdf(
            image_paths,
            output_file,
            progress_callback=progress_callback,
            progress_state=progress_state,
        )
        processed_image_paths.extend(image_paths)
        output_files.append((output_file, len(image_paths)))

    if delete_after_use:
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


def main() -> None:
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    args = parse_args()
    startup_error: str | None = None
    initial_mode = resolve_initial_mode(args.mode)
    initial_delete_after_use = resolve_initial_delete_after_use(args.delete_after_use)

    try:
        initial_input_dir = resolve_initial_input_dir(args.input_dir)
    except Exception as exc:
        initial_input_dir = None
        startup_error = str(exc)

    root = tk.Tk()
    root.title("Image to PDF")
    root.geometry("860x620")
    root.minsize(760, 520)
    root.configure(bg="#f3f6fb")

    style = ttk.Style()
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("App.TFrame", background="#f3f6fb")
    style.configure("Card.TFrame", background="#ffffff")
    style.configure(
        "Title.TLabel",
        background="#f3f6fb",
        foreground="#102a43",
        font=("Arial", 18, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        background="#f3f6fb",
        foreground="#486581",
        font=("Arial", 10),
    )
    style.configure(
        "Section.TLabel",
        background="#ffffff",
        foreground="#102a43",
        font=("Arial", 11, "bold"),
    )
    style.configure(
        "Body.TLabel",
        background="#ffffff",
        foreground="#334e68",
        font=("Arial", 10),
    )
    style.configure(
        "Status.TLabel",
        background="#ffffff",
        foreground="#1f2933",
        font=("Arial", 10, "bold"),
    )
    style.configure("Primary.TButton", font=("Arial", 10, "bold"))
    style.configure("Secondary.TButton", font=("Arial", 10))

    frame = ttk.Frame(root, padding=20, style="App.TFrame")
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text="Tạo PDF từ ảnh",
        style="Title.TLabel",
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "Chỉ xử lý các ảnh có tên dạng timestamp_xx-xxxxxxxx.* "
            "và có thể xuất thành một PDF duy nhất hoặc nhiều PDF theo tiền tố timestamp_xx."
        ),
        style="Subtitle.TLabel",
        wraplength=800,
        justify="left",
    ).pack(anchor="w", pady=(6, 18))

    control_card = ttk.Frame(frame, padding=18, style="Card.TFrame")
    control_card.pack(fill="x")

    ttk.Label(control_card, text="Thư mục ảnh", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        control_card,
        text="Ứng dụng sẽ nhớ thư mục bạn chọn gần nhất cho lần mở sau.",
        style="Body.TLabel",
        wraplength=780,
        justify="left",
    ).pack(anchor="w", pady=(4, 10))

    selected_dir_var = tk.StringVar(value=str(initial_input_dir) if initial_input_dir else "")
    output_dir_var = tk.StringVar(value=str(resolve_output_dir(args.output).resolve()))
    mode_var = tk.StringVar(value=initial_mode)
    delete_after_use_var = tk.BooleanVar(value=initial_delete_after_use)
    status_var = tk.StringVar(value="Sẵn sàng.")
    progress_text_var = tk.StringVar(value="Chưa bắt đầu xử lý.")

    dir_row = ttk.Frame(control_card, style="Card.TFrame")
    dir_row.pack(fill="x")

    dir_entry = ttk.Entry(dir_row, textvariable=selected_dir_var, font=("Arial", 10))
    dir_entry.pack(side="left", fill="x", expand=True)
    choose_dir_button = ttk.Button(
        dir_row,
        text="Chọn thư mục",
        style="Secondary.TButton",
        command=lambda: on_choose_dir(),
    )
    choose_dir_button.pack(side="left", padx=(12, 0))

    button_row = ttk.Frame(control_card, style="Card.TFrame")
    button_row.pack(fill="x", pady=(12, 0))

    ttk.Label(control_card, text="Thư mục output", style="Section.TLabel").pack(
        anchor="w", pady=(14, 0)
    )
    ttk.Label(
        control_card,
        textvariable=output_dir_var,
        style="Body.TLabel",
        wraplength=780,
        justify="left",
    ).pack(anchor="w", pady=(4, 0))

    ttk.Label(control_card, text="Chế độ xuất", style="Section.TLabel").pack(
        anchor="w", pady=(14, 0)
    )
    mode_row = ttk.Frame(control_card, style="Card.TFrame")
    mode_row.pack(fill="x", pady=(6, 0))

    merge_mode_radio = ttk.Radiobutton(
        mode_row,
        text="Gộp tất cả ảnh thành 1 PDF",
        value=MODE_MERGE_ALL,
        variable=mode_var,
    )
    merge_mode_radio.pack(side="left")
    split_mode_radio = ttk.Radiobutton(
        mode_row,
        text="Tách nhiều PDF theo tiền tố",
        value=MODE_SPLIT_BY_PREFIX,
        variable=mode_var,
    )
    split_mode_radio.pack(side="left", padx=(18, 0))

    delete_after_use_checkbox = ttk.Checkbutton(
        control_card,
        text="Xóa ảnh sau khi tạo PDF thành công",
        variable=delete_after_use_var,
    )
    delete_after_use_checkbox.pack(anchor="w", pady=(12, 0))

    results_card = ttk.Frame(frame, padding=18, style="Card.TFrame")
    results_card.pack(fill="both", expand=True, pady=(16, 0))

    ttk.Label(results_card, text="Kết quả", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        results_card,
        text="Thông báo xử lý, lỗi và danh sách file PDF sẽ hiển thị tại đây.",
        style="Body.TLabel",
        wraplength=780,
        justify="left",
    ).pack(anchor="w", pady=(4, 10))

    result_box = scrolledtext.ScrolledText(
        results_card,
        wrap="word",
        font=("Arial", 10),
        height=18,
        padx=10,
        pady=10,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground="#d9e2ec",
    )
    result_box.pack(fill="both", expand=True)
    result_box.configure(state="disabled")

    progress_row = ttk.Frame(results_card, style="Card.TFrame")
    progress_row.pack(fill="x", pady=(12, 0))
    progress_bar = ttk.Progressbar(progress_row, mode="determinate", maximum=100, value=0)
    progress_bar.pack(fill="x")
    ttk.Label(
        progress_row,
        textvariable=progress_text_var,
        style="Body.TLabel",
        wraplength=780,
        justify="left",
    ).pack(anchor="w", pady=(6, 0))

    status_row = ttk.Frame(results_card, style="Card.TFrame")
    status_row.pack(fill="x", pady=(12, 0))
    ttk.Label(status_row, textvariable=status_var, style="Status.TLabel").pack(anchor="w")

    def set_controls_enabled(enabled: bool) -> None:
        state = "!disabled" if enabled else "disabled"
        for widget in (
            dir_entry,
            choose_dir_button,
            merge_mode_radio,
            split_mode_radio,
            delete_after_use_checkbox,
            create_button,
        ):
            widget.state([state] if enabled else ["disabled"])

    def update_progress(current: int, total: int, message: str) -> None:
        total_value = max(total, 1)
        progress_bar.configure(maximum=total_value)
        progress_bar["value"] = min(current, total_value)
        progress_text_var.set(f"{message} ({min(current, total_value)}/{total_value})")
        root.update()

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

    def on_build_pdfs() -> None:
        raw_dir = selected_dir_var.get().strip()
        selected_mode = mode_var.get()
        delete_after_use = delete_after_use_var.get()
        if not raw_dir:
            set_result("Bạn chưa chọn thư mục ảnh.\nHãy bấm “Chọn thư mục” để tiếp tục.", is_error=True)
            return

        input_dir = Path(raw_dir).expanduser()
        if not input_dir.exists() or not input_dir.is_dir():
            set_result(f"Thư mục không tồn tại:\n{input_dir}", is_error=True)
            return

        try:
            status_var.set("Đang tạo PDF...")
            update_progress(0, 1, "Đang chuẩn bị xử lý...")
            set_controls_enabled(False)
            root.update_idletasks()
            save_last_input_dir(input_dir)
            save_last_mode(selected_mode)
            save_delete_after_use(delete_after_use)
            output_files = build_pdfs(
                input_dir,
                args.output,
                selected_mode,
                delete_after_use=delete_after_use,
                progress_callback=update_progress,
            )
        except Exception as exc:
            set_controls_enabled(True)
            set_result(str(exc), is_error=True)
            return

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
            f"Thư mục output: {resolve_output_dir(args.output).resolve()}\n"
            f"Chế độ xuất: {mode_text}\n"
            f"Xóa ảnh sau khi tạo PDF: {delete_text}\n"
            f"Số file PDF đã tạo: {total_files}\n"
            f"Tổng số ảnh đã xử lý: {total_images}\n\n"
            f"{deleted_summary}"
            f"Chi tiết:\n{details}"
        )
        set_controls_enabled(True)

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
                + f"\nXóa ảnh sau khi tạo PDF: {'Có' if initial_delete_after_use else 'Không'}",
                status_message="Sẵn sàng.",
            )
        except Exception as exc:
            set_result(str(exc), is_error=True, status_message="Có lỗi xảy ra.")
    else:
        set_result(
            "Chào bạn.\n\nHãy chọn thư mục chứa ảnh, chọn chế độ xuất rồi nhấn “Tạo PDF”.",
            status_message="Sẵn sàng.",
        )

    progress_text_var.set("Chưa bắt đầu xử lý.")

    if startup_error:
        set_result(startup_error, is_error=True)

    dir_entry.focus_set()

    root.mainloop()


if __name__ == "__main__":
    main()
