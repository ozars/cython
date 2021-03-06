#!/usr/bin/env python

from __future__ import absolute_import

import os
import shutil
import tempfile
from distutils.core import setup

from .Dependencies import cythonize, extended_iglob
from ..Utils import is_package_dir
from ..Compiler import Options

try:
    import multiprocessing
    parallel_compiles = int(multiprocessing.cpu_count() * 1.5)
except ImportError:
    multiprocessing = None
    parallel_compiles = 0


class _FakePool(object):
    def map_async(self, func, args):
        try:
            from itertools import imap
        except ImportError:
            imap=map
        for _ in imap(func, args):
            pass

    def close(self):
        pass

    def terminate(self):
        pass

    def join(self):
        pass


def find_package_base(path):
    base_dir, package_path = os.path.split(path)
    while is_package_dir(base_dir):
        base_dir, parent = os.path.split(base_dir)
        package_path = '%s/%s' % (parent, package_path)
    return base_dir, package_path


def cython_compile(path_pattern, options):
    pool = None
    all_paths = map(os.path.abspath, extended_iglob(path_pattern))
    try:
        for path in all_paths:
            if options.build_inplace:
                base_dir = path
                while not os.path.isdir(base_dir) or is_package_dir(base_dir):
                    base_dir = os.path.dirname(base_dir)
            else:
                base_dir = None

            if os.path.isdir(path):
                # recursively compiling a package
                paths = [os.path.join(path, '**', '*.{py,pyx}')]
            else:
                # assume it's a file(-like thing)
                paths = [path]

            ext_modules = cythonize(
                paths,
                nthreads=options.parallel,
                exclude_failures=options.keep_going,
                exclude=options.excludes,
                compiler_directives=options.directives,
                compile_time_env=options.compile_time_env,
                force=options.force,
                quiet=options.quiet,
                **options.options)

            if ext_modules and options.build:
                if len(ext_modules) > 1 and options.parallel > 1:
                    if pool is None:
                        try:
                            pool = multiprocessing.Pool(options.parallel)
                        except OSError:
                            pool = _FakePool()
                    pool.map_async(run_distutils, [
                        (base_dir, [ext]) for ext in ext_modules])
                else:
                    run_distutils((base_dir, ext_modules))
    except:
        if pool is not None:
            pool.terminate()
        raise
    else:
        if pool is not None:
            pool.close()
            pool.join()


def run_distutils(args):
    base_dir, ext_modules = args
    script_args = ['build_ext', '-i']
    cwd = os.getcwd()
    temp_dir = None
    try:
        if base_dir:
            os.chdir(base_dir)
            temp_dir = tempfile.mkdtemp(dir=base_dir)
            script_args.extend(['--build-temp', temp_dir])
        setup(
            script_name='setup.py',
            script_args=script_args,
            ext_modules=ext_modules,
        )
    finally:
        if base_dir:
            os.chdir(cwd)
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir)


def create_args_parser():
    from argparse import ArgumentParser, Action

    class ParseDirectivesAction(Action):
        def __call__(self, parser, namespace, values, option_string=None):
            old_directives = dict(getattr(namespace, self.dest,
                                          Options.get_directive_defaults()))
            directives = Options.parse_directive_list(
                values, relaxed_bool=True, current_settings=old_directives)
            setattr(namespace, self.dest, directives)

    class ParseOptionsAction(Action):
        def __call__(self, parser, namespace, values, option_string=None):
            options = dict(getattr(namespace, self.dest, {}))
            for opt in values.split(','):
                if '=' in opt:
                    n, v = opt.split('=', 1)
                    v = v.lower() not in ('false', 'f', '0', 'no')
                else:
                    n, v = opt, True
                options[n] = v
            setattr(namespace, self.dest, options)

    class ParseCompileTimeEnvAction(Action):
        def __call__(self, parser, namespace, values, option_string=None):
            old_env = dict(getattr(namespace, self.dest, {}))
            new_env = Options.parse_compile_time_env(values, current_settings=old_env)
            setattr(namespace, self.dest, new_env)

    parser = ArgumentParser()

    parser.add_argument('-X', '--directive', metavar='NAME=VALUE,...',
                      dest='directives', default={}, type=str,
                      action=ParseDirectivesAction,
                      help='set a compiler directive')
    parser.add_argument('-E', '--compile-time-env', metavar='NAME=VALUE,...',
                      dest='compile_time_env', default={}, type=str,
                      action=ParseCompileTimeEnvAction,
                      help='set a compile time environment variable')
    parser.add_argument('-s', '--option', metavar='NAME=VALUE',
                      dest='options', default={}, type=str,
                      action=ParseOptionsAction,
                      help='set a cythonize option')
    parser.add_argument('-2', dest='language_level', action='store_const', const=2, default=None,
                      help='use Python 2 syntax mode by default')
    parser.add_argument('-3', dest='language_level', action='store_const', const=3,
                      help='use Python 3 syntax mode by default')
    parser.add_argument('--3str', dest='language_level', action='store_const', const='3str',
                      help='use Python 3 syntax mode by default')
    parser.add_argument('-a', '--annotate', action='store_const', const='default', dest='annotate',
                      help='Produce a colorized HTML version of the source.')
    parser.add_argument('--annotate-fullc', action='store_const', const='fullc', dest='annotate',
                      help='Produce a colorized HTML version of the source '
                           'which includes entire generated C/C++-code.')
    parser.add_argument('-x', '--exclude', metavar='PATTERN', dest='excludes',
                      action='append', default=[],
                      help='exclude certain file patterns from the compilation')

    parser.add_argument('-b', '--build', dest='build', action='store_true', default=None,
                      help='build extension modules using distutils')
    parser.add_argument('-i', '--inplace', dest='build_inplace', action='store_true', default=None,
                      help='build extension modules in place using distutils (implies -b)')
    parser.add_argument('-j', '--parallel', dest='parallel', metavar='N',
                      type=int, default=parallel_compiles,
                      help=('run builds in N parallel jobs (default: %d)' %
                            parallel_compiles or 1))
    parser.add_argument('-f', '--force', dest='force', action='store_true', default=None,
                      help='force recompilation')
    parser.add_argument('-q', '--quiet', dest='quiet', action='store_true', default=None,
                      help='be less verbose during compilation')

    parser.add_argument('--lenient', dest='lenient', action='store_true', default=None,
                      help='increase Python compatibility by ignoring some compile time errors')
    parser.add_argument('-k', '--keep-going', dest='keep_going', action='store_true', default=None,
                      help='compile as much as possible, ignore compilation failures')
    parser.add_argument('--no-docstrings', dest='no_docstrings', action='store_true', default=None,
                      help='strip docstrings')
    parser.add_argument('sources', nargs='*')
    return parser


def parse_args_raw(parser, args):
    options, unknown = parser.parse_known_args(args)
    sources = options.sources
    # if positional arguments were interspersed
    # some of them are in unknown
    for option in unknown:
        if option.startswith('-'):
            parser.error("unknown option "+option)
        else:
            sources.append(option)
    del options.sources
    return (options, sources)


def parse_args(args):
    parser = create_args_parser()
    options, args = parse_args_raw(parser, args)
    if not args:
        parser.error("no source files provided")
    if options.build_inplace:
        options.build = True
    if multiprocessing is None:
        options.parallel = 0
    if options.language_level:
        assert options.language_level in (2, 3, '3str')
        options.options['language_level'] = options.language_level
    return options, args


def main(args=None):
    options, paths = parse_args(args)

    if options.lenient:
        # increase Python compatibility by ignoring compile time errors
        Options.error_on_unknown_names = False
        Options.error_on_uninitialized = False

    if options.annotate:
        Options.annotate = True

    if options.no_docstrings:
        Options.docstrings = False

    for path in paths:
        cython_compile(path, options)


if __name__ == '__main__':
    main()
