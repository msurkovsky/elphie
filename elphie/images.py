from elphie.svg import RendererSVG, run_inkscape
from elphie.elements import PaddingLessBox
from elphie.theme import Theme
from elphie.textstyle import TextStyle
# from elphie.slides import Context

import subprocess
import os
import sys
import pickle
import argparse
from math import ceil
from concurrent.futures import ThreadPoolExecutor


class Image(object):

    role = None
    extra_data = None

    def __init__(self, filename, theme, width, height, preferDrawingSize):
        self.filename = filename
        self.element = PaddingLessBox("main")
        self.theme = theme
        self.preferDrawingSize=preferDrawingSize
        self._width = width
        self._heigh = height

    def width(self, ctx):
        if self.preferDrawingSize:
            width = self.element.get_size_request(ctx).width
            if width == 0:
                return self._width
            return ceil(width)
        return self._width

    def height(self, ctx):
        if self.preferDrawingSize:
            height = self.element.get_size_request(ctx).height
            if height == 0:
                return self._heigh
            return ceil(height)
        return self._heigh

    def get_max_step(self):
        return self.element.get_max_step()

    def gather_queries(self, ctx):
        queries = []
        self.element.gather_queries(ctx, queries)
        return queries


class Context(object):

    def __init__(self,
                 renderer,
                 theme,
                 image,
                 step,
                 query_cache,
                 text_styles,
                 workers=None):
        self.renderer = renderer
        self.theme = theme
        self.image = image
        self.step = step
        self.stack = []
        self.query_cache = query_cache
        self.workers = workers
        self.text_styles = theme.text_styles.copy()
        for name, style in text_styles.items():
            self.text_styles[name] = style

    def get_query(self, key):
        try:
            return self.query_cache[key]
        except KeyError:
            print("Queries:")
            for q in self.query_cache:
                print(q)
            print("Searching for: ", key)
            raise Exception("Invalid query key")

    def push(self, obj):
        self.stack.append(obj)

    def pop(self):
        self.stack.pop()


class Images:

    def __init__(self,
                 defaultWidth,
                 defaultHeight,
                 theme=None,
                 output_dir="./elphie-svg",
                 cache_dir="./elphie-cache",
                 parse_args=True,
                 debug=False,
                 threads=None):

        self.defaultWidth = defaultWidth
        self.defaultHeight = defaultHeight
        self.images = []
        if theme:
            self.theme = theme
        else:
            self.theme = Theme()
        self.output_dir = output_dir
        self.cache_dir = cache_dir
        self.user_defined_text_styles = {}
        self.debug = debug
        self.threads = threads

        if parse_args:
            self._parse_args()

    def new_image(self,
                  filename=None,
                  theme=None,
                  width=None,
                  height=None,
                  preferDrawingSize=True):
        return self._make_image(
            filename, theme, width, height, preferDrawingSize).element

    def _make_image(self, filename, theme, width, height, preferDrawingSize):
        if theme is None:
            theme = self.theme
        if width is None:
            width = self.defaultWidth
        if height is None:
            height = self.defaultHeight

        image = Image(filename, theme, width, height, preferDrawingSize)
        self.images.append(image)
        return image

    def _show_progress(
            self, name, value=0, max_value=0, first=False, last=False):
        if not first:
            prefix = "\r"
        else:
            prefix = ""
        if last:
            progress = "done"
            suffix = "\n"
        else:
            if max_value != 0 and not first:
                progress = str(int(value * 100.0 / max_value)) + "%"
            else:
                progress = ""
            suffix = ""
        if self.debug:
            prefix = ""
            suffix = "\n"
        name = name.ljust(30, ".")
        sys.stdout.write("{}{} {}{}".format(prefix, name, progress, suffix))
        sys.stdout.flush()

    def render(self):
        # Create directories
        if not os.path.isdir(self.cache_dir):
            print("Creating cache directory: ", self.cache_dir)
            os.makedirs(self.cache_dir)

        if not os.path.isdir(self.output_dir):
            print("Creating cache directory: ", self.output_dir)
            os.makedirs(self.output_dir)

        if not self.images:
            raise Exception("No images to render")

        # Gather image queries
        renderer = RendererSVG()
        queries = []
        old_query_cache = self._load_query_cache()
        query_cache = {}

        for image in self.images:
            ctx = Context(renderer, image.theme, image, None, None,
                          self.user_defined_text_styles)
            for query in image.gather_queries(ctx):
                key = query[0]
                value = old_query_cache.get(key)
                if value is not None:
                    query_cache[key] = value
                else:
                    queries.append(query)
        queries = dict(queries)

        # Create threads
        threads = self.threads
        if threads is None:
            threads = os.cpu_count() or 1
        pool = ThreadPoolExecutor(threads)

        # Process new queries
        self._show_progress("Preprocessing", first=True)
        count = 0
        for key, result in pool.map(
                lambda query: (query[0], query[1]()), queries.items()):
            query_cache[key] = result
            count += 1
            self._show_progress("Preprocessing", count, len(queries))
        self._show_progress("Preprocessing", count, len(queries), last=True)
        self._save_query_cache(query_cache)

        contexts = []
        for i, image in enumerate(self.images):
            for step in range(image.get_max_step()):
                renderer = RendererSVG()
                ctx = Context(
                    renderer, image.theme, image, step + 1, query_cache,
                    self.user_defined_text_styles)
                renderer.begin(image.width(ctx), image.height(ctx))
                contexts.append(ctx)

        # Build images
        self._show_progress("Building", first=True)
        count = 0
        for filename in pool.map(
                lambda ctx: self.render_image(ctx),
                contexts):
            count += 1
            self._show_progress("Building", count, len(contexts))
        self._show_progress("Building", count, len(contexts), last=True)

    def set_style(self, name, style):
        assert isinstance(name, str)
        assert isinstance(style, TextStyle)
        self.user_defined_text_styles[name] = style

    def render_image(self, ctx):
        width = ctx.image.width(ctx)
        height = ctx.image.height(ctx)

        ctx.renderer.begin(width, height)
        ctx.theme.render_raw_image(ctx)
        ctx.renderer.end()

        filename = os.path.join(self.output_dir, "{}-{}-{}.svg".format(
            ctx.image.filename, self.images.index(ctx.image), ctx.step))
        ctx.renderer.write(filename)

        return filename

    def _load_query_cache(self):
        filename = os.path.join(self.cache_dir, "queries")
        try:
            with open(filename, "rb") as f:
                query_cache = pickle.load(f)
                print("Cache loaded")
                return query_cache
        except FileNotFoundError:  # noqa
            print("No cache file found")
            return {}

    def _save_query_cache(self, query_cache):
        filename = os.path.join(self.cache_dir, "queries")
        try:
            with open(filename, "wb") as f:
                pickle.dump(query_cache, f)
        except:
            print("Cache cannot be written ")

    def _parse_args(self):
        parser = argparse.ArgumentParser(description="Elphie")
        parser.add_argument("--debug",
                            action="store_true",
                            default=self.debug,
                            help="Enable debug mode")
        parser.add_argument("--threads",
                            type=int,
                            default=self.threads,
                            help="Number of used threads "
                                 "(default: autodetect)")
        args = parser.parse_args()
        self.debug = args.debug
        self.threads = args.threads
