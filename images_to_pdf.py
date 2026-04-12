from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageOps


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_NAME_PATTERN = re.compile(r"^(?P<group>\d+_\d{2})-(?P<index>\d{8})$")
CONFIG_FILE = Path.home() / ".image_to_pdf_config.json"


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


def load_last_input_dir() -> Path | None:
    if not CONFIG_FILE.exists():
        return None

    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    input_dir = config.get("last_input_dir")
    if not input_dir:
        return None

    path = Path(input_dir).expanduser()
    return path if path.exists() and path.is_dir() else None


def save_last_input_dir(input_dir: Path) -> None:
    config = {"last_input_dir": str(input_dir.resolve())}
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


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


def load_image_groups(input_dir: Path) -> dict[str, list[Path]]:
    image_paths = sorted(path for path in input_dir.iterdir() if is_supported_image(path))

    if not image_paths:
        raise FileNotFoundError(
            "Không tìm thấy ảnh hợp lệ trong thư mục: "
            f"{input_dir}\nTên file phải có dạng timestamp_xx-xxxxxxxx"
        )

    groups: dict[str, list[Path]] = {}
    for image_path in image_paths:
        group_name = get_image_group(image_path)
        groups.setdefault(group_name, []).append(image_path)

    return groups


def load_pdf_pages(image_paths: list[Path]) -> list[Image.Image]:
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

    return pages


def save_pdf(image_paths: list[Path], output_file: Path) -> None:
    pages = load_pdf_pages(image_paths)
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


def build_pdfs(input_dir: Path, output_path: Path) -> list[tuple[Path, int]]:
    image_groups = load_image_groups(input_dir)
    output_files: list[tuple[Path, int]] = []

    for group_name, image_paths in image_groups.items():
        output_file = resolve_output_file(output_path, group_name)
        save_pdf(image_paths, output_file)
        output_files.append((output_file, len(image_paths)))

    return output_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Xoay ảnh ngang thành dọc và gộp ảnh thành các file PDF theo nhóm."
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


def main() -> None:
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    args = parse_args()
    startup_error: str | None = None

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
        text="Tạo PDF từ ảnh theo nhóm timestamp_xx",
        style="Title.TLabel",
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "Chỉ xử lý các ảnh có tên dạng timestamp_xx-xxxxxxxx.* "
            "và xuất ra file PDF theo tên timestamp_xx.pdf."
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
    status_var = tk.StringVar(value="Sẵn sàng.")

    dir_row = ttk.Frame(control_card, style="Card.TFrame")
    dir_row.pack(fill="x")

    dir_entry = ttk.Entry(dir_row, textvariable=selected_dir_var, font=("Arial", 10))
    dir_entry.pack(side="left", fill="x", expand=True)
    ttk.Button(
        dir_row,
        text="Chọn thư mục",
        style="Secondary.TButton",
        command=lambda: on_choose_dir(),
    ).pack(side="left", padx=(12, 0))

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

    status_row = ttk.Frame(results_card, style="Card.TFrame")
    status_row.pack(fill="x", pady=(12, 0))
    ttk.Label(status_row, textvariable=status_var, style="Status.TLabel").pack(anchor="w")

    def set_result(message: str, *, is_error: bool = False) -> None:
        result_box.configure(state="normal")
        result_box.delete("1.0", tk.END)
        result_box.insert("1.0", message)
        result_box.configure(
            state="disabled",
            foreground="#8a1c1c" if is_error else "#243b53",
        )
        status_var.set("Có lỗi xảy ra." if is_error else "Đã hoàn thành.")

    def on_choose_dir() -> None:
        current_dir = Path(selected_dir_var.get()).expanduser() if selected_dir_var.get() else None
        selected_dir = choose_input_dir(root, current_dir or load_last_input_dir())
        if selected_dir is None:
            return

        selected_dir_var.set(str(selected_dir))
        save_last_input_dir(selected_dir)
        status_var.set("Đã cập nhật thư mục ảnh.")

    def on_build_pdfs() -> None:
        raw_dir = selected_dir_var.get().strip()
        if not raw_dir:
            set_result("Bạn chưa chọn thư mục ảnh.\nHãy bấm “Chọn thư mục” để tiếp tục.", is_error=True)
            return

        input_dir = Path(raw_dir).expanduser()
        if not input_dir.exists() or not input_dir.is_dir():
            set_result(f"Thư mục không tồn tại:\n{input_dir}", is_error=True)
            return

        try:
            status_var.set("Đang tạo PDF...")
            root.update_idletasks()
            save_last_input_dir(input_dir)
            output_files = build_pdfs(input_dir, args.output)
        except Exception as exc:
            set_result(str(exc), is_error=True)
            return

        total_files = len(output_files)
        total_images = sum(image_count for _, image_count in output_files)
        details = "\n".join(
            f"- {output_file.name}: {image_count} ảnh\n  {output_file}"
            for output_file, image_count in output_files
        )
        set_result(
            f"Tạo PDF thành công.\n\n"
            f"Thư mục nguồn: {input_dir}\n"
            f"Thư mục output: {resolve_output_dir(args.output).resolve()}\n"
            f"Số file PDF đã tạo: {total_files}\n"
            f"Tổng số ảnh đã xử lý: {total_images}\n\n"
            f"Chi tiết:\n{details}"
        )

    ttk.Button(
        button_row,
        text="Tạo PDF",
        style="Primary.TButton",
        command=on_build_pdfs,
    ).pack(side="left")
    ttk.Button(
        button_row,
        text="Đóng",
        style="Secondary.TButton",
        command=root.destroy,
    ).pack(side="right")

    if initial_input_dir is not None:
        set_result(
            "Ứng dụng đã sẵn sàng.\n\n"
            f"Thư mục đang chọn:\n{initial_input_dir}\n\n"
            "Nhấn “Tạo PDF” để bắt đầu, hoặc “Chọn thư mục” để đổi thư mục khác."
        )
    else:
        set_result("Chào bạn.\n\nHãy chọn thư mục chứa ảnh rồi nhấn “Tạo PDF”.")

    if startup_error:
        set_result(startup_error, is_error=True)

    dir_entry.focus_set()

    root.mainloop()


if __name__ == "__main__":
    main()
