import hashlib
import logging
import sys
from pathlib import Path
from cli import parse_args


def setup_simple_logger(work_dir):
    """Создает простой логгер для вывода в консоль и файл."""
    logger = logging.getLogger("unbraid")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("[%(levelname)s] %(message)s")

    c_handler = logging.StreamHandler()
    c_handler.setFormatter(fmt)
    logger.addHandler(c_handler)

    f_handler = logging.FileHandler(
        work_dir / "unbraid.log", mode="w", encoding="utf-8")
    f_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(f_handler)

    return logger

def get_project_context():
    """Автоматически находит целевой файл и собирает контекст проекта."""
    cli_path_str, _ = parse_args()
    cli_path = Path(cli_path_str).resolve() if cli_path_str else Path.cwd()

    if cli_path.is_file():
        target_file = cli_path
    elif cli_path.is_dir():
        # Список стандартных точек входа по приоритету
        possible_mains = ["main.py", "main_test.py", "app.py"]
        target_file = None
        
        for name in possible_mains:
            if (cli_path / name).exists():
                target_file = cli_path / name
                break
                
        if not target_file:
            print(f"[ERROR] В папке {cli_path} не найден файл точки входа.")
            sys.exit(1)
    else:
        print(f"[ERROR] Указанный путь не существует: {cli_path}")
        sys.exit(1)

    project_root = target_file.parent
    sys.path.insert(0, str(project_root))

    # Создаем изолированную папку кэша по хэшу пути (без привязки к именам)
    tool_root = Path(__file__).resolve().parent
    path_hash = hashlib.md5(str(target_file).encode()).hexdigest()[:6]
    output_dir = tool_root / "projects" / f"{target_file.stem}_{path_hash}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Инициализируем наш сквозной логгер
    logger = setup_simple_logger(output_dir)

    return {
        "target_file": target_file,
        "project_root": project_root,
        "output_dir": output_dir,
        "logger": logger
    }

