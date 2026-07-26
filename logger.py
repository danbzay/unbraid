import logging

LOG_NAME = "unbraid.log"


def setup_logger(work_dir):
    """Настраивает логгер: выводит инфо в консоль, а детали — в файл."""
    work_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("unbraid")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    c_format = logging.Formatter("[%(levelname)s] %(message)s")
    f_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(filename)s: %(message)s"
    )

    c_handler = logging.StreamHandler()
    c_handler.setFormatter(c_format)
    logger.addHandler(c_handler)

    f_handler = logging.FileHandler(work_dir / LOG_NAME, encoding="utf-8")
    f_handler.setFormatter(f_format)
    logger.addHandler(f_handler)

    return logger
