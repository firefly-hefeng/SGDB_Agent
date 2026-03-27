#!/usr/bin/env python3
"""Minimal tqdm stub for compatibility when tqdm is not installed."""

import sys


class tqdm:
    """A simple tqdm-compatible progress bar."""
    
    def __init__(self, iterable=None, desc=None, total=None, **kwargs):
        self.iterable = iterable
        self.desc = desc
        self.total = total
        self.n = 0
        if desc:
            print(f"{desc}: ", end="", file=sys.stderr)
    
    def __iter__(self):
        for item in self.iterable:
            self.n += 1
            yield item
        self.close()
    
    def update(self, n=1):
        self.n += n
    
    def close(self):
        if self.desc:
            count = self.total if self.total else self.n
            print(f"Done ({count} items)", file=sys.stderr)
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


def trange(*args, **kwargs):
    """Range with progress bar."""
    return tqdm(range(*args), **kwargs)
