import argparse


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dir", help="Путь к файлу или папке")
    parser.add_argument("-c", "--config", help="Путь к конфигу")
    args = parser.parse_args()
    return args.dir, args.config

