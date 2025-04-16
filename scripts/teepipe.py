#!/usr/bin/env python3
#
# tee, but for pipes
#
# Example:
# ./scripts/tee.py in_pipe out_pipe1 out_pipe2
#
# Copyright (c) 2022, The littlefs authors.
# SPDX-License-Identifier: BSD-3-Clause
#

# prevent local imports
if __name__ == "__main__":
    __import__('sys').path.pop(0)

import os
import io
import time
import sys


# open with '-' for stdin/stdout
def openio(path, mode='r', buffering=-1):
    import os
    if path == '-':
        if 'r' in mode:
            return os.fdopen(os.dup(sys.stdin.fileno()), mode, buffering)
        else:
            return os.fdopen(os.dup(sys.stdout.fileno()), mode, buffering)
    else:
        return open(path, mode, buffering)

def main(in_path, out_paths, *, keep_open=False):
    out_pipes = [openio(p, 'wb', 0) for p in out_paths]
    try:
        with openio(in_path, 'rb', 0) as f:
            while True:
                buf = f.read(io.DEFAULT_BUFFER_SIZE)
                if not buf:
                    if not keep_open:
                        break
                    # don't just flood reads
                    time.sleep(0.1)
                    continue

                for p in out_pipes:
                    try:
                        p.write(buf)
                    except BrokenPipeError:
                        pass
    except FileNotFoundError as e:
        print("error: file not found %r" % in_path,
                file=sys.stderr)
        sys.exit(-1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser(
            description="tee, but for pipes.",
            allow_abbrev=False)
    parser.add_argument(
            'in_path',
            help="Path to read from.")
    parser.add_argument(
            'out_paths',
            nargs='+',
            help="Path to write to.")
    parser.add_argument(
            '-k', '--keep-open',
            action='store_true',
            help="Reopen the pipe on EOF, useful when multiple "
                "processes are writing.")
    sys.exit(main(**{k: v
            for k, v in vars(parser.parse_intermixed_args()).items()
            if v is not None}))
