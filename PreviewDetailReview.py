"""Inspect remaining Pixel Accurate errors in two aligned, read-only plan views."""
from contextlib import closing
import logging
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk


def review_data(plan):
    if not isinstance(plan, dict):
        return None
    metadata = plan.get('options', {}).get('pixel_accuracy_meta') or {}
    regions = (metadata.get('region_accuracy') or {}).get('preview_detail_regions')
    views = plan.get('ui_previews') or {}
    if (regions and regions.get('regions') and
            all(isinstance(views.get(key), Image.Image) for key in ('quantized_target', 'simulated_final'))):
        return regions
    return None


def region_view(size, bbox, viewport):
    """Return a shared normalized crop and its undistorted display dimensions."""
    width, height = size
    x0, y0, x1, y1 = bbox
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError('Missed-detail region is outside its measured grid.')
    margin = max(2, round(max(x1 - x0, y1 - y0) / 8))
    left, top = max(0, x0 - margin), max(0, y0 - margin)
    right, bottom = min(width, x1 + margin), min(height, y1 + margin)
    crop_width, crop_height = right - left, bottom - top
    scale = min(viewport[0] / crop_width, viewport[1] / crop_height)
    display = (max(1, round(scale * crop_width)), max(1, round(scale * crop_height)))
    return (left / width, top / height, right / width, bottom / height), display


def detail_photo(image, crop, size, make_photo):
    box = (crop[0] * image.width, crop[1] * image.height,
           crop[2] * image.width, crop[3] * image.height)
    with closing(image.resize(size, Image.Resampling.NEAREST, box=box)) as pixels:
        return make_photo(pixels)


class PreviewDetailReview(ttk.Frame):
    def __init__(self, parent, anchor, current_plan):
        super().__init__(parent)
        self._anchor = anchor
        self._current_plan = current_plan
        self._data = None
        self._photos = ()
        heading = ttk.Frame(self)
        heading.pack(fill='x')
        ttk.Label(heading, text='Missed details').pack(side='left', padx=(0, 8))
        self.selector = ttk.Combobox(heading, state='readonly', width=18,
                                     style='ImageDrawBot.TCombobox', takefocus=True)
        self.selector.pack(side='left', fill='x', expand=True)
        self.selector.bind('<<ComboboxSelected>>', self.select)
        self.comparison = ttk.Frame(self)
        self.comparison.columnconfigure((0, 1), weight=1, uniform='detail')
        self.panes = []
        for column, name in enumerate(('Quantized target', 'Simulated final')):
            ttk.Label(self.comparison, text=name, anchor='center').grid(row=0, column=column, sticky='ew')
            pane = ttk.Label(self.comparison, anchor='center')
            pane.grid(row=1, column=column, sticky='nsew')
            self.panes.append(pane)
        self.metrics = ttk.Label(self.comparison, anchor='center', justify='center', wraplength=340)
        self.metrics.grid(row=2, column=0, columnspan=2, sticky='ew')

    def _hide_comparison(self):
        self.comparison.pack_forget()
        for pane in self.panes:
            pane.configure(image='')
        self._photos = ()

    def clear(self):
        if self._data is None:
            return
        self._data = None
        self._hide_comparison()
        self.selector.set('')
        self.selector.configure(values=())
        self.pack_forget()

    def publish(self, plan):
        self.clear()
        data = review_data(plan)
        if data is None:
            return
        choices = ['Choose a region']
        for index, region in enumerate(data['regions'][:3], 1):
            left, top = region['bbox'][:2]
            choices.append(f'{index}. ({left}, {top}) · {region["protected_error_pixels"]:,} missed detail px')
        self._data = data
        self.selector.configure(values=choices)
        self.selector.current(0)
        self.pack(after=self._anchor, fill='x', padx=16, pady=(0, 7))

    def select(self, _event=None):
        plan = self._current_plan()
        if self._data is None or self._data is not review_data(plan):
            self.clear()
            return
        index = self.selector.current() - 1
        self._hide_comparison()
        if not 0 <= index < min(3, len(self._data['regions'])):
            return
        region = self._data['regions'][index]
        # Bound both Tk uploads even for a multi-megapixel scoring grid.
        viewport = (max(1, min(256, (self.winfo_width() - 8) // 2)), 144)
        try:
            crop, display = region_view(self._data['size'], region['bbox'], viewport)
            photos = tuple(detail_photo(plan['ui_previews'][key], crop, display,
                                        lambda pixels: ImageTk.PhotoImage(pixels, master=self))
                           for key in ('quantized_target', 'simulated_final'))
            if self._current_plan() is not plan:
                self.clear()
                return
            for pane, photo in zip(self.panes, photos):
                pane.configure(image=photo)
        except (OSError, ValueError, MemoryError, tk.TclError) as error:
            self._hide_comparison()
            self.metrics.configure(text='This detail could not be displayed.')
            logging.getLogger(__name__).warning('Could not render missed detail: %s', error)
        else:
            self._photos = photos
            self.metrics.configure(text=(f'Component error · {region["missing_pixels"]:,} uncovered · '
                                         f'{region["wrong_color_pixels"]:,} wrong color'))
        self.comparison.pack(fill='x', pady=(4, 0))

    def destroy(self):
        try:
            super().destroy()
        finally:
            self._current_plan = self._anchor = self._data = None
            self._photos = ()
            self.panes.clear()
            self.selector = self.comparison = self.metrics = None
