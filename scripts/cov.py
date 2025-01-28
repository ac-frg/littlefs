#!/usr/bin/env python3
#
# Script to find coverage info after running tests.
#
# Example:
# ./scripts/cov.py \
#         lfs.t.a.gcda lfs_util.t.a.gcda \
#         -Flfs.c -Flfs_util.c -slines
#
# Copyright (c) 2022, The littlefs authors.
# Copyright (c) 2020, Arm Limited. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
#

# prevent local imports
if __name__ == "__main__":
    __import__('sys').path.pop(0)

import collections as co
import csv
import itertools as it
import json
import math as mt
import os
import re
import shlex
import subprocess as sp


# TODO use explode_asserts to avoid counting assert branches?
# TODO use dwarf=info to find functions for inline functions?

GCOV_PATH = ['gcov']


# integer fields
class RInt(co.namedtuple('RInt', 'x')):
    __slots__ = ()
    def __new__(cls, x=0):
        if isinstance(x, RInt):
            return x
        if isinstance(x, str):
            try:
                x = int(x, 0)
            except ValueError:
                # also accept +-∞ and +-inf
                if re.match('^\s*\+?\s*(?:∞|inf)\s*$', x):
                    x = mt.inf
                elif re.match('^\s*-\s*(?:∞|inf)\s*$', x):
                    x = -mt.inf
                else:
                    raise
        if not (isinstance(x, int) or mt.isinf(x)):
            x = int(x)
        return super().__new__(cls, x)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.x)

    def __str__(self):
        if self.x == mt.inf:
            return '∞'
        elif self.x == -mt.inf:
            return '-∞'
        else:
            return str(self.x)

    def __bool__(self):
        return bool(self.x)

    def __int__(self):
        assert not mt.isinf(self.x)
        return self.x

    def __float__(self):
        return float(self.x)

    none = '%7s' % '-'
    def table(self):
        return '%7s' % (self,)

    def diff(self, other):
        new = self.x if self else 0
        old = other.x if other else 0
        diff = new - old
        if diff == +mt.inf:
            return '%7s' % '+∞'
        elif diff == -mt.inf:
            return '%7s' % '-∞'
        else:
            return '%+7d' % diff

    def ratio(self, other):
        new = self.x if self else 0
        old = other.x if other else 0
        if mt.isinf(new) and mt.isinf(old):
            return 0.0
        elif mt.isinf(new):
            return +mt.inf
        elif mt.isinf(old):
            return -mt.inf
        elif not old and not new:
            return 0.0
        elif not old:
            return +mt.inf
        else:
            return (new-old) / old

    def __pos__(self):
        return self.__class__(+self.x)

    def __neg__(self):
        return self.__class__(-self.x)

    def __abs__(self):
        return self.__class__(abs(self.x))

    def __add__(self, other):
        return self.__class__(self.x + other.x)

    def __sub__(self, other):
        return self.__class__(self.x - other.x)

    def __mul__(self, other):
        return self.__class__(self.x * other.x)

    def __truediv__(self, other):
        if not other:
            if self >= self.__class__(0):
                return self.__class__(+mt.inf)
            else:
                return self.__class__(-mt.inf)
        return self.__class__(self.x // other.x)

    def __mod__(self, other):
        return self.__class__(self.x % other.x)

# fractional fields, a/b
class RFrac(co.namedtuple('RFrac', 'a,b')):
    __slots__ = ()
    def __new__(cls, a=0, b=None):
        if isinstance(a, RFrac) and b is None:
            return a
        if isinstance(a, str) and b is None:
            a, b = a.split('/', 1)
        if b is None:
            b = a
        return super().__new__(cls, RInt(a), RInt(b))

    def __repr__(self):
        return '%s(%r, %r)' % (self.__class__.__name__, self.a.x, self.b.x)

    def __str__(self):
        return '%s/%s' % (self.a, self.b)

    def __bool__(self):
        return bool(self.a)

    def __int__(self):
        return int(self.a)

    def __float__(self):
        return float(self.a)

    none = '%11s' % '-'
    def table(self):
        return '%11s' % (self,)

    def notes(self):
        t = self.a.x/self.b.x if self.b.x else 1.0
        return ['∞%' if t == +mt.inf
                else '-∞%' if t == -mt.inf
                else '%.1f%%' % (100*t)]

    def diff(self, other):
        new_a, new_b = self if self else (RInt(0), RInt(0))
        old_a, old_b = other if other else (RInt(0), RInt(0))
        return '%11s' % ('%s/%s' % (
                new_a.diff(old_a).strip(),
                new_b.diff(old_b).strip()))

    def ratio(self, other):
        new_a, new_b = self if self else (RInt(0), RInt(0))
        old_a, old_b = other if other else (RInt(0), RInt(0))
        new = new_a.x/new_b.x if new_b.x else 1.0
        old = old_a.x/old_b.x if old_b.x else 1.0
        return new - old

    def __pos__(self):
        return self.__class__(+self.a, +self.b)

    def __neg__(self):
        return self.__class__(-self.a, -self.b)

    def __abs__(self):
        return self.__class__(abs(self.a), abs(self.b))

    def __add__(self, other):
        return self.__class__(self.a + other.a, self.b + other.b)

    def __sub__(self, other):
        return self.__class__(self.a - other.a, self.b - other.b)

    def __mul__(self, other):
        return self.__class__(self.a * other.a, self.b * other.b)

    def __truediv__(self, other):
        return self.__class__(self.a / other.a, self.b / other.b)

    def __mod__(self, other):
        return self.__class__(self.a % other.a, self.b % other.b)

    def __eq__(self, other):
        self_a, self_b = self if self.b.x else (RInt(1), RInt(1))
        other_a, other_b = other if other.b.x else (RInt(1), RInt(1))
        return self_a * other_b == other_a * self_b

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        self_a, self_b = self if self.b.x else (RInt(1), RInt(1))
        other_a, other_b = other if other.b.x else (RInt(1), RInt(1))
        return self_a * other_b < other_a * self_b

    def __gt__(self, other):
        return self.__class__.__lt__(other, self)

    def __le__(self, other):
        return not self.__gt__(other)

    def __ge__(self, other):
        return not self.__lt__(other)

# coverage results
class CovResult(co.namedtuple('CovResult', [
        'file', 'function', 'line',
        'calls', 'hits', 'funcs', 'lines', 'branches'])):
    _by = ['file', 'function', 'line']
    _fields = ['calls', 'hits', 'funcs', 'lines', 'branches']
    _sort = ['funcs', 'lines', 'branches', 'hits', 'calls']
    _types = {
            'calls': RInt, 'hits': RInt,
            'funcs': RFrac, 'lines': RFrac, 'branches': RFrac}

    __slots__ = ()
    def __new__(cls, file='', function='', line=0,
            calls=0, hits=0, funcs=0, lines=0, branches=0):
        return super().__new__(cls, file, function, int(RInt(line)),
                RInt(calls), RInt(hits),
                RFrac(funcs), RFrac(lines), RFrac(branches))

    def __add__(self, other):
        return CovResult(self.file, self.function, self.line,
                max(self.calls, other.calls),
                max(self.hits, other.hits),
                self.funcs + other.funcs,
                self.lines + other.lines,
                self.branches + other.branches)


def openio(path, mode='r', buffering=-1):
    # allow '-' for stdin/stdout
    if path == '-':
        if 'r' in mode:
            return os.fdopen(os.dup(sys.stdin.fileno()), mode, buffering)
        else:
            return os.fdopen(os.dup(sys.stdout.fileno()), mode, buffering)
    else:
        return open(path, mode, buffering)

def collect_cov(gcda_path, *,
        gcov_path=GCOV_PATH,
        **args):
    # get coverage info through gcov's json output
    # note, gcov-path may contain extra args
    cmd = GCOV_PATH + ['-b', '-t', '--json-format', gcda_path]
    if args.get('verbose'):
        print(' '.join(shlex.quote(c) for c in cmd))
    proc = sp.Popen(cmd,
            stdout=sp.PIPE,
            universal_newlines=True,
            errors='replace',
            close_fds=False)
    cov = json.load(proc.stdout)
    proc.wait()
    if proc.returncode != 0:
        raise sp.CalledProcessError(proc.returncode, proc.args)

    return cov

def collect(gcda_paths, *,
        sources=None,
        everything=False,
        **args):
    results = []
    for gcda_path in gcda_paths:
        # find coverage info
        cov = collect_cov(gcda_path, **args)

        # collect line/branch coverage
        for file in cov['files']:
            # ignore filtered sources
            if sources is not None:
                if not any(os.path.abspath(file['file']) == os.path.abspath(s)
                        for s in sources):
                    continue
            else:
                # default to only cwd
                if not everything and not os.path.commonpath([
                        os.getcwd(),
                        os.path.abspath(file['file'])]) == os.getcwd():
                    continue

            # simplify path
            if os.path.commonpath([
                    os.getcwd(),
                    os.path.abspath(file['file'])]) == os.getcwd():
                file_name = os.path.relpath(file['file'])
            else:
                file_name = os.path.abspath(file['file'])

            for func in file['functions']:
                func_name = func.get('name', '(inlined)')
                # discard internal functions (this includes injected test cases)
                if not everything and func_name.startswith('__'):
                    continue

                # go ahead and add functions, later folding will merge this if
                # there are other hits on this line
                results.append(CovResult(
                        file_name, func_name, func['start_line'],
                        func['execution_count'], 0,
                        RFrac(1 if func['execution_count'] > 0 else 0, 1),
                        0,
                        0))

            for line in file['lines']:
                func_name = line.get('function_name', '(inlined)')
                # discard internal function (this includes injected test cases)
                if not everything and func_name.startswith('__'):
                    continue

                # go ahead and add lines, later folding will merge this if
                # there are other hits on this line
                results.append(CovResult(
                        file_name, func_name, line['line_number'],
                        0, line['count'],
                        0,
                        RFrac(1 if line['count'] > 0 else 0, 1),
                        RFrac(
                            sum(1 if branch['count'] > 0 else 0
                                for branch in line['branches']),
                            len(line['branches']))))

    return results


def fold(Result, results, by=None, defines=[]):
    if by is None:
        by = Result._by

    for k in it.chain(by or [], (k for k, _ in defines)):
        if k not in Result._by and k not in Result._fields:
            print("error: could not find field %r?" % k,
                    file=sys.stderr)
            sys.exit(-1)

    # filter by matching defines
    if defines:
        results_ = []
        for r in results:
            if all(getattr(r, k) in vs for k, vs in defines):
                results_.append(r)
        results = results_

    # organize results into conflicts
    folding = co.OrderedDict()
    for r in results:
        name = tuple(getattr(r, k) for k in by)
        if name not in folding:
            folding[name] = []
        folding[name].append(r)

    # merge conflicts
    folded = []
    for name, rs in folding.items():
        folded.append(sum(rs[1:], start=rs[0]))

    return folded

def table(Result, results, diff_results=None, *,
        by=None,
        fields=None,
        sort=None,
        diff=None,
        percent=None,
        all=False,
        compare=None,
        no_header=False,
        small_header=False,
        no_total=False,
        small_table=False,
        summary=False,
        depth=1,
        hot=None,
        **_):
    all_, all = all, __builtins__.all

    if by is None:
        by = Result._by
    if fields is None:
        fields = Result._fields
    types = Result._types

    # fold again
    results = fold(Result, results, by=by)
    if diff_results is not None:
        diff_results = fold(Result, diff_results, by=by)

    # reduce children to hot paths? only used by some scripts
    if hot:
        # subclass to reintroduce __dict__
        Result_ = Result
        class HotResult(Result_):
            _i = '_hot_i'
            _children = '_hot_children'

            def __new__(cls, r, i=None, children=None, notes=None):
                self = HotResult._make(r)
                self._hot_i = i
                self._hot_children = children if children is not None else []
                return self

            def __add__(self, other):
                return HotResult(
                        Result_.__add__(self, other),
                        self._hot_i if other._hot_i is None
                            else other._hot_i if self._hot_i is None
                            else min(self._hot_i, other._hot_i),
                        self._hot_children + other._hot_children)

        results_ = []
        for r in results:
            hot_ = []
            def recurse(results_, depth_):
                nonlocal hot_
                if not results_:
                    return

                # find the hottest result
                r = max(results_,
                        key=lambda r: tuple(
                            tuple((getattr(r, k),)
                                        if getattr(r, k, None) is not None
                                        else ()
                                    for k in (
                                        [k] if k else [
                                            k for k in Result._sort
                                                if k in fields])
                                    if k in fields)
                                for k in it.chain(hot, [None])))
                hot_.append(HotResult(r, i=len(hot_)))

                # recurse?
                if depth_ > 1:
                    recurse(getattr(r, Result._children),
                            depth_-1)

            recurse(getattr(r, Result._children), depth-1)
            results_.append(HotResult(r, children=hot_))

        Result = HotResult
        results = results_

    # organize by name
    table = {
            ','.join(str(getattr(r, k) or '') for k in by): r
                for r in results}
    diff_table = {
            ','.join(str(getattr(r, k) or '') for k in by): r
                for r in diff_results or []}
    names = [name
            for name in table.keys() | diff_table.keys()
            if diff_results is None
                or all_
                or any(
                    types[k].ratio(
                            getattr(table.get(name), k, None),
                            getattr(diff_table.get(name), k, None))
                        for k in fields)]

    # find compare entry if there is one
    if compare:
        compare_result = table.get(','.join(str(k) for k in compare))

    # sort again, now with diff info, note that python's sort is stable
    names.sort()
    if compare:
        names.sort(
                key=lambda n: (
                    # move compare entry to the top, note this can be
                    # overridden by explicitly sorting by fields
                    table.get(n) == compare_result,
                    # sort by ratio if comparing
                    tuple(
                        types[k].ratio(
                                getattr(table.get(n), k, None),
                                getattr(compare_result, k, None))
                            for k in fields)),
                reverse=True)
    if diff or percent:
        names.sort(
                # sort by ratio if diffing
                key=lambda n: tuple(
                    types[k].ratio(
                            getattr(table.get(n), k, None),
                            getattr(diff_table.get(n), k, None))
                        for k in fields),
                reverse=True)
    if sort:
        for k, reverse in reversed(sort):
            names.sort(
                    key=lambda n: tuple(
                        (getattr(table[n], k),)
                                if getattr(table.get(n), k, None) is not None
                                else ()
                            for k in (
                                [k] if k else [
                                    k for k in Result._sort
                                        if k in fields])),
                    reverse=reverse ^ (not k or k in Result._fields))


    # build up our lines
    lines = []

    # header
    if not no_header:
        header = ['%s%s' % (
                    ','.join(by),
                    ' (%d added, %d removed)' % (
                            sum(1 for n in table if n not in diff_table),
                            sum(1 for n in diff_table if n not in table))
                        if diff else '')
                if not small_header and not small_table and not summary
                    else '']
        if not diff:
            for k in fields:
                header.append(k)
        else:
            for k in fields:
                header.append('o'+k)
            for k in fields:
                header.append('n'+k)
            for k in fields:
                header.append('d'+k)
        lines.append(header)

    # entry helper
    def table_entry(name, r, diff_r=None):
        entry = [name]
        # normal entry?
        if ((compare is None or r == compare_result)
                and not percent
                and not diff):
            for k in fields:
                entry.append(
                        (getattr(r, k).table(),
                                getattr(getattr(r, k), 'notes', lambda: [])())
                            if getattr(r, k, None) is not None
                            else types[k].none)
        # compare entry?
        elif not percent and not diff:
            for k in fields:
                entry.append(
                        (getattr(r, k).table()
                                if getattr(r, k, None) is not None
                                else types[k].none,
                            (lambda t: ['+∞%'] if t == +mt.inf
                                    else ['-∞%'] if t == -mt.inf
                                    else ['%+.1f%%' % (100*t)])(
                                types[k].ratio(
                                    getattr(r, k, None),
                                    getattr(compare_result, k, None)))))
        # percent entry?
        elif not diff:
            for k in fields:
                entry.append(
                        (getattr(r, k).table()
                                if getattr(r, k, None) is not None
                                else types[k].none,
                            (lambda t: ['+∞%'] if t == +mt.inf
                                    else ['-∞%'] if t == -mt.inf
                                    else ['%+.1f%%' % (100*t)])(
                                types[k].ratio(
                                    getattr(r, k, None),
                                    getattr(diff_r, k, None)))))
        # diff entry?
        else:
            for k in fields:
                entry.append(getattr(diff_r, k).table()
                        if getattr(diff_r, k, None) is not None
                        else types[k].none)
            for k in fields:
                entry.append(getattr(r, k).table()
                        if getattr(r, k, None) is not None
                        else types[k].none)
            for k in fields:
                entry.append(
                        (types[k].diff(
                                getattr(r, k, None),
                                getattr(diff_r, k, None)),
                            (lambda t: ['+∞%'] if t == +mt.inf
                                    else ['-∞%'] if t == -mt.inf
                                    else ['%+.1f%%' % (100*t)] if t
                                    else [])(
                                types[k].ratio(
                                    getattr(r, k, None),
                                    getattr(diff_r, k, None)))))
        # append any notes
        if hasattr(Result, '_notes') and r is not None:
            notes = sorted(getattr(r, Result._notes))
            if isinstance(entry[-1], tuple):
                entry[-1] = (entry[-1][0], entry[-1][1] + notes)
            else:
                entry[-1] = (entry[-1], notes)

        return entry

    # recursive entry helper, only used by some scripts
    def recurse(results_, depth_,
            prefixes=('', '', '', '')):
        # build the children table at each layer
        results_ = fold(Result, results_, by=by)
        table_ = {
                ','.join(str(getattr(r, k) or '') for k in by): r
                    for r in results_}
        names_ = list(table_.keys())

        # sort the children layer
        names_.sort()
        if hasattr(Result, '_i'):
            names_.sort(key=lambda n: getattr(table_[n], Result._i))
        if sort:
            for k, reverse in reversed(sort):
                names_.sort(
                        key=lambda n: tuple(
                            (getattr(table_[n], k),)
                                    if getattr(table_.get(n), k, None)
                                        is not None
                                    else ()
                                for k in (
                                    [k] if k else [
                                        k for k in Result._sort
                                            if k in fields])),
                        reverse=reverse ^ (not k or k in Result._fields))

        for i, name in enumerate(names_):
            r = table_[name]
            is_last = (i == len(names_)-1)

            line = table_entry(name, r)
            line = [x if isinstance(x, tuple) else (x, []) for x in line]
            # add prefixes
            line[0] = (prefixes[0+is_last] + line[0][0], line[0][1])
            lines.append(line)

            # recurse?
            if depth_ > 1:
                recurse(getattr(r, Result._children),
                        depth_-1,
                        (prefixes[2+is_last] + "|-> ",
                         prefixes[2+is_last] + "'-> ",
                         prefixes[2+is_last] + "|   ",
                         prefixes[2+is_last] + "    "))

    # entries
    if not summary:
        for name in names:
            r = table.get(name)
            if diff_results is None:
                diff_r = None
            else:
                diff_r = diff_table.get(name)
            lines.append(table_entry(name, r, diff_r))

            # recursive entries
            if name in table and depth > 1:
                recurse(getattr(table[name], Result._children),
                        depth-1,
                        ("|-> ",
                         "'-> ",
                         "|   ",
                         "    "))

    # total
    if not no_total and not (small_table and not summary):
        r = next(iter(fold(Result, results, by=[])), None)
        if diff_results is None:
            diff_r = None
        else:
            diff_r = next(iter(fold(Result, diff_results, by=[])), None)
        lines.append(table_entry('TOTAL', r, diff_r))

    # homogenize
    lines = [
            [x if isinstance(x, tuple) else (x, []) for x in line]
                for line in lines]

    # find the best widths, note that column 0 contains the names and is
    # handled a bit differently
    widths = co.defaultdict(lambda: 7, {0: 7})
    nwidths = co.defaultdict(lambda: 0)
    for line in lines:
        for i, x in enumerate(line):
            widths[i] = max(widths[i], ((len(x[0])+1+4-1)//4)*4-1)
            if i != len(line)-1:
                nwidths[i] = max(nwidths[i], 1+sum(2+len(n) for n in x[1]))

    # print our table
    for line in lines:
        print('%-*s  %s' % (
                widths[0], line[0][0],
                ' '.join('%*s%-*s' % (
                        widths[i], x[0],
                        nwidths[i], ' (%s)' % ', '.join(x[1]) if x[1] else '')
                    for i, x in enumerate(line[1:], 1))))


def annotate(Result, results, *,
        annotate=False,
        lines=False,
        branches=False,
        **args):
    # if neither branches/lines specified, color both
    if annotate and not lines and not branches:
        lines, branches = True, True

    for path in co.OrderedDict.fromkeys(r.file for r in results).keys():
        # flatten to line info
        results = fold(Result, results, by=['file', 'line'])
        table = {r.line: r for r in results if r.file == path}

        # calculate spans to show
        if not annotate:
            spans = []
            last = None
            func = None
            for line, r in sorted(table.items()):
                if ((lines and int(r.hits) == 0)
                        or (branches and r.branches.a < r.branches.b)):
                    if last is not None and line - last.stop <= args['context']:
                        last = range(
                                last.start,
                                line+1+args['context'])
                    else:
                        if last is not None:
                            spans.append((last, func))
                        last = range(
                                line-args['context'],
                                line+1+args['context'])
                        func = r.function
            if last is not None:
                spans.append((last, func))

        with open(path) as f:
            skipped = False
            for i, line in enumerate(f):
                # skip lines not in spans?
                if not annotate and not any(i+1 in s for s, _ in spans):
                    skipped = True
                    continue

                if skipped:
                    skipped = False
                    print('%s@@ %s:%d: %s @@%s' % (
                            '\x1b[36m' if args['color'] else '',
                            path,
                            i+1,
                            next(iter(f for _, f in spans)),
                            '\x1b[m' if args['color'] else ''))

                # build line
                if line.endswith('\n'):
                    line = line[:-1]

                if i+1 in table:
                    r = table[i+1]
                    line = '%-*s // %s hits%s' % (
                            args['width'],
                            line,
                            r.hits,
                            ', %s branches' % (r.branches,)
                                if int(r.branches.b) else '')

                    if args['color']:
                        if lines and int(r.hits) == 0:
                            line = '\x1b[1;31m%s\x1b[m' % line
                        elif branches and r.branches.a < r.branches.b:
                            line = '\x1b[35m%s\x1b[m' % line

                print(line)


def main(gcda_paths, *,
        by=None,
        fields=None,
        defines=[],
        sort=None,
        hits=False,
        **args):
    # figure out what color should be
    if args.get('color') == 'auto':
        args['color'] = sys.stdout.isatty()
    elif args.get('color') == 'always':
        args['color'] = True
    else:
        args['color'] = False

    # find sizes
    if not args.get('use', None):
        # not enough info?
        if not gcda_paths:
            print("error: no *.gcda files?",
                    file=sys.stderr)
            sys.exit(1)

        # collect info
        results = collect(gcda_paths, **args)

    else:
        results = []
        with openio(args['use']) as f:
            reader = csv.DictReader(f, restval='')
            for r in reader:
                # filter by matching defines
                if not all(k in r and r[k] in vs for k, vs in defines):
                    continue

                if not any(k in r and r[k].strip()
                        for k in CovResult._fields):
                    continue
                try:
                    results.append(CovResult(
                            **{k: r[k] for k in CovResult._by
                                if k in r and r[k].strip()},
                            **{k: r[k]
                                for k in CovResult._fields
                                if k in r and r[k].strip()}))
                except TypeError:
                    pass

    # fold
    results = fold(CovResult, results, by=by, defines=defines)

    # sort, note that python's sort is stable
    results.sort()
    if sort:
        for k, reverse in reversed(sort):
            results.sort(
                    key=lambda r: tuple(
                        (getattr(r, k),) if getattr(r, k) is not None else ()
                            for k in ([k] if k else CovResult._sort)),
                    reverse=reverse ^ (not k or k in CovResult._fields))

    # write results to CSV
    if args.get('output'):
        with openio(args['output'], 'w') as f:
            writer = csv.DictWriter(f,
                    (by if by is not None else CovResult._by)
                        + [k for k in (
                            fields if fields is not None
                                else CovResult._fields)])
            writer.writeheader()
            for r in results:
                writer.writerow(
                        {k: getattr(r, k) for k in (
                                by if by is not None else CovResult._by)}
                            | {k: getattr(r, k) for k in (
                                fields if fields is not None
                                    else CovResult._fields)})

    # find previous results?
    diff_results = None
    if args.get('diff') or args.get('percent'):
        diff_results = []
        try:
            with openio(args.get('diff') or args.get('percent')) as f:
                reader = csv.DictReader(f, restval='')
                for r in reader:
                    # filter by matching defines
                    if not all(k in r and r[k] in vs for k, vs in defines):
                        continue

                    if not any(k in r and r[k].strip()
                            for k in CovResult._fields):
                        continue
                    try:
                        diff_results.append(CovResult(
                                **{k: r[k] for k in CovResult._by
                                    if k in r and r[k].strip()},
                                **{k: r[k] for k in CovResult._fields
                                    if k in r and r[k].strip()}))
                    except TypeError:
                        pass
        except FileNotFoundError:
            pass

        # fold
        diff_results = fold(CovResult, diff_results, by=by, defines=defines)

    # print table
    if not args.get('quiet'):
        if (args.get('annotate')
                or args.get('lines')
                or args.get('branches')):
            # annotate sources
            annotate(CovResult, results, **args)
        else:
            # print table
            table(CovResult, results, diff_results,
                    by=by if by is not None else ['function'],
                    fields=fields if fields is not None
                        else ['lines', 'branches'] if not hits
                        else ['calls', 'hits'],
                    sort=sort,
                    **args)

    # catch lack of coverage
    if args.get('error_on_lines') and any(
            r.lines.a < r.lines.b for r in results):
        sys.exit(2)
    elif args.get('error_on_branches') and any(
            r.branches.a < r.branches.b for r in results):
        sys.exit(3)


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser(
            description="Find coverage info after running tests.",
            allow_abbrev=False)
    parser.add_argument(
            'gcda_paths',
            nargs='*',
            help="Input *.gcda files.")
    parser.add_argument(
            '-v', '--verbose',
            action='store_true',
            help="Output commands that run behind the scenes.")
    parser.add_argument(
            '-q', '--quiet',
            action='store_true',
            help="Don't show anything, useful with -o.")
    parser.add_argument(
            '-o', '--output',
            help="Specify CSV file to store results.")
    parser.add_argument(
            '-u', '--use',
            help="Don't parse anything, use this CSV file.")
    parser.add_argument(
            '-d', '--diff',
            help="Specify CSV file to diff against.")
    parser.add_argument(
            '-p', '--percent',
            help="Specify CSV file to diff against, but only show precentage "
                "change, not a full diff.")
    parser.add_argument(
            '-a', '--all',
            action='store_true',
            help="Show all, not just the ones that changed.")
    parser.add_argument(
            '-c', '--compare',
            type=lambda x: tuple(v.strip() for v in x.split(',')),
            help="Compare results to the row matching this by pattern.")
    parser.add_argument(
            '-b', '--by',
            action='append',
            choices=CovResult._by,
            help="Group by this field.")
    parser.add_argument(
            '-f', '--field',
            dest='fields',
            action='append',
            choices=CovResult._fields,
            help="Show this field.")
    parser.add_argument(
            '-D', '--define',
            dest='defines',
            action='append',
            type=lambda x: (
                lambda k, vs: (
                    k.strip(),
                    {v.strip() for v in vs.split(',')})
                )(*x.split('=', 1)),
            help="Only include results where this field is this value.")
    class AppendSort(argparse.Action):
        def __call__(self, parser, namespace, value, option):
            if namespace.sort is None:
                namespace.sort = []
            namespace.sort.append((value, True if option == '-S' else False))
    parser.add_argument(
            '-s', '--sort',
            nargs='?',
            action=AppendSort,
            help="Sort by this field.")
    parser.add_argument(
            '-S', '--reverse-sort',
            nargs='?',
            action=AppendSort,
            help="Sort by this field, but backwards.")
    parser.add_argument(
            '--no-header',
            action='store_true',
            help="Don't show the header.")
    parser.add_argument(
            '--small-header',
            action='store_true',
            help="Don't show by field names.")
    parser.add_argument(
            '--no-total',
            action='store_true',
            help="Don't show the total.")
    parser.add_argument(
            '-Q', '--small-table',
            action='store_true',
            help="Equivalent to --small-header + --no-total.")
    parser.add_argument(
            '-Y', '--summary',
            action='store_true',
            help="Only show the total.")
    parser.add_argument(
            '-F', '--source',
            dest='sources',
            action='append',
            help="Only consider definitions in this file. Defaults to "
                "anything in the current directory.")
    parser.add_argument(
            '--everything',
            action='store_true',
            help="Include builtin and libc specific symbols.")
    parser.add_argument(
            '--hits',
            action='store_true',
            help="Show total hits instead of coverage.")
    parser.add_argument(
            '-A', '--annotate',
            action='store_true',
            help="Show source files annotated with coverage info.")
    parser.add_argument(
            '-L', '--lines',
            action='store_true',
            help="Show uncovered lines.")
    parser.add_argument(
            '-B', '--branches',
            action='store_true',
            help="Show uncovered branches.")
    parser.add_argument(
            '-C', '--context',
            type=lambda x: int(x, 0),
            default=3,
            help="Show n additional lines of context. Defaults to 3.")
    parser.add_argument(
            '-W', '--width',
            type=lambda x: int(x, 0),
            default=80,
            help="Assume source is styled with this many columns. Defaults "
                "to 80.")
    parser.add_argument(
            '--color',
            choices=['never', 'always', 'auto'],
            default='auto',
            help="When to use terminal colors. Defaults to 'auto'.")
    parser.add_argument(
            '-e', '--error-on-lines',
            action='store_true',
            help="Error if any lines are not covered.")
    parser.add_argument(
            '-E', '--error-on-branches',
            action='store_true',
            help="Error if any branches are not covered.")
    parser.add_argument(
            '--gcov-path',
            default=GCOV_PATH,
            type=lambda x: x.split(),
            help="Path to the gcov executable, may include paths. "
                "Defaults to %r." % GCOV_PATH)
    sys.exit(main(**{k: v
            for k, v in vars(parser.parse_intermixed_args()).items()
            if v is not None}))
