#!/usr/bin/python
# -*- coding: utf-8 -*-
import keyring
import logging
import gkeepapi
import curses
import yaml
import locale

from uuid import getnode as get_mac

locale.setlocale(locale.LC_ALL, '')

def ellipsize(text, max_len):
    if len(text) <= max_len:
        return text

    return text[:max_len - 1] + u'⋯'

class UI(object):
    def __init__(self, parent_win):
        self.parent_win = parent_win
        self.focus = None

    def resize(self, w, h):
        self.win.resize(h, w)

    def move(self, x, y):
        self.win.mvderwin(y, x)

    def process(self, c):
        if self.focus is not None:
            if self.focus.process(c):
                return True

        return False

    def setFocus(self, element):
        self.focus = element

    def getSize(self):
        h, w = self.win.getmaxyx()
        return w, h

class ListUI(UI):
    def __init__(self, parent_win, child_clazz, borders=(0, 0, 0, 0), elements=[], margin=1, columns=1):
        super(ListUI, self).__init__(parent_win)
        self._createWin()
        self.margin = margin
        self.borders = borders
        self.elements = []
        self.columns = columns
        self.column_widths = []
        self.child_clazz = child_clazz
        self.active = 0
        self._last_width = 0

        self.setElements(elements)
        self._computeColumnWidths()

    def _createWin(self):
        self.win = self.parent_win.derwin(0, 0)

    def _computeColumnWidths(self):
        max_x, _ = self.getSize()
        if max_x == self._last_width:
            return

        self._last_width = max_x
        min_x = self.borders[2]
        max_x -= self.borders[3]

        width = (max_x - min_x) / self.columns
        self.column_widths = []
        for i in range(self.columns):
            self.column_widths.append((i * width, (i + 1) * width - 1))
        logging.error(self.column_widths)

    def resize(self, w, h):
        super(ListUI, self).resize(w, h)
        self._computeColumnWidths()

    def setElements(self, elements):
        self.elements = [self.child_clazz(self.win, element) for element in elements]
        self._changeActive(0)

    def render(self):
        column_heights = [[i, self.borders[0]] for i in range(self.columns)]

        _, max_y = self.getSize()
        max_y -= self.borders[1]
        for element in self.getElements():
            if not column_heights:
                continue

            i, curr_y = column_heights[0]
            height = element.getHeight()
            if max_y < curr_y + height:
                height = max_y - curr_y
            min_x, max_x = self.column_widths[i]
            element.resize(max_x - min_x, height)
            element.move(min_x, curr_y)
            element.render()

            column_heights[0][1] += height + self.margin
            if column_heights[0][1] >= max_y:
                column_heights = column_heights[1:]
            else:
                column_heights.sort(key=lambda x: x[1])

        self.win.noutrefresh()

    def process(self, c):
        if super(ListUI, self).process(c):
            return True

        if   c == ord('j') or c == curses.KEY_DOWN:
            self._changeActive(+1)

        elif c == ord('k') or c == curses.KEY_UP:
            self._changeActive(-1)

        elif c == ord('e'):
            self._toggleArchived(self.active)

        elif c == ord('f'):
            self._togglePinned(self.active)

        elif c == curses.KEY_ENTER:
            pass

        return False

    def getElements(self):
        return self.elements

    def _togglePinned(self, i):
        element = self.getElements()[i]
        element.note.pinned = not element.note.pinned

    def _toggleArchived(self, i):
        element = self.getElements()[i]
        element.note.archived = not element.note.archived

    def _changeActive(self, delta):
        elements = self.getElements()
        if not elements:
            self.active = 0
            return

        elements[self.active].setActive(False)
        self.active = (self.active + delta) % len(elements)
        elements[self.active].setActive(True)

class ItemUI(UI):
    def __init__(self, parent_win, listitem):
        super(ItemUI, self).__init__(parent_win)
        self.listitem = listitem

class NoteUI(ListUI):
    def __init__(self, parent_win, note):
        super(NoteUI, self).__init__(parent_win, ItemUI, borders=(1, 0, 0, 0), elements=[], margin=0, columns=1)
        self.note = note
        self.active = False
        self.selected = False
        self._updateHighlight()

    def _createWin(self):
        self.win = self.parent_win.derwin(0, 0, 0, 0)

    def _updateHighlight(self):
        num = 1
        if self.active:
            num = 2

        if self.selected:
            num = 3

        self.win.bkgdset(' ', curses.color_pair(num))

    def setActive(self, active):
        self.active = active
        self._updateHighlight()

    def setSelected(self, selected):
        self.selected = selected
        self._updateHighlight()

    def getHeight(self):
        total = 1
        if type(self.note) == gkeepapi.node.Note:
            total += 1 + self.note.text.count("\n")
        else:
            total += len(self.note.items)
        return total

    def render(self):
        max_x, max_y = self.getSize()

        # Fill background
        for i in range(max_y):
            try:
                self.win.addstr(i, 0, ' ' * max_x)
            except curses.error:
                pass

        text_index = self.borders[0]
        if not self.note.title:
            text_index += 1
        else:
            title_size = max_x
            if title_size > 3:
                title_size -= 3

                try:
                    self.win.addstr(
                        0, title_size + 1,
                        ('⊔' if self.note.archived else ' ') +
                        ('○' if self.note.pinned else ' '),
                        curses.color_pair(2)
                    )
                except curses.error:
                    pass

            try:
                self.win.addstr(
                    0, 0,
                    ellipsize(self.note.title, max_x - 3).encode('UTF-8'),
                    curses.A_UNDERLINE
                )
            except curses.error:
                pass

        if max_y > text_index:
            if type(self.note) == gkeepapi.node.Note:
                entries = [ellipsize(line, max_x) for line in self.note.text.split("\n")]
            else:
                entries = [
                    (u'☒' if item.checked else u'☐') + ellipsize(item.text, max_x - 1) for item in self.note.items
                ]
            for i in range(min(max_y - text_index, len(entries))):
                try:
                    self.win.addstr(
                        i + text_index, 0,
                        entries[i].encode('UTF-8'),
                    )
                except curses.error:
                    pass
        self.win.noutrefresh()

class NoteListUI(ListUI):
    def __init__(self, parent_win, borders=(0, 0, 0, 0), elements=[], margin=1, columns=1):
        super(NoteListUI, self).__init__(parent_win, NoteUI, borders=(0, 0, 0, 0), elements=elements, margin=1, columns=2)

class KeepUI(object):
    def __init__(self, win, keep, config):
        self.win = win
        self.keep = keep
        self.config = config
        self.list_ui = ListUI(self.win, NoteUI, columns=1)
        self.refresh()

        curses.curs_set(0)
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)

    def refresh(self):
        self.keep.sync()

        todo = self.keep.findLabel('todo')
        notes = self.keep.find(archived=False, trashed=False, labels=[todo])
        notes = filter(lambda note: note.id not in self.config['ignore'], notes)
        self.list_ui.setElements(notes)

    def process(self):
        while True:
            self.win.erase()
            self.list_ui.render()
            self.win.refresh()

            c = self.win.getch()
            self.list_ui.process(c)
            if c == curses.KEY_RESIZE:
                h, w = self.win.getmaxyx()
                self.list_ui.resize(w, h)
            elif c == ord('r'):
                self.refresh()
            elif c == curses.KEY_MOUSE:
                pass

def main(stdscr):
    fh = open('config.yml', 'r')
    config = yaml.load(fh, Loader=yaml.Loader)
    fh.close()

    password = keyring.get_password('google-keep', config['username'])

    keep = gkeepapi.Keep()
    keep.login(config['username'], password)

    ui = KeepUI(stdscr, keep, config)
    ui.process()

curses.wrapper(main)
