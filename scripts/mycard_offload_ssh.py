#!/usr/bin/env python3
"""Forced SSH command for the home MyCard archive pull key."""
import os
from pathlib import Path
import shlex
import sys

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
from services.mycard_archive.offload import main


def allowed_command(text):
    args = shlex.split(text)
    if args in (["mycard-offload", "prepare"], ["mycard-offload", "status"]):
        return args[1:]
    if len(args) == 3 and args[:2] == ["mycard-offload", "fetch"]:
        return args[1:]
    if len(args) == 4 and args[:2] == ["mycard-offload", "commit"]:
        return args[1:]
    raise ValueError("This key is restricted to MyCard archive transfer")


if __name__ == "__main__":
    main(allowed_command(os.getenv("SSH_ORIGINAL_COMMAND", "")))
